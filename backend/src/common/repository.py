"""Persistence layer.

Two interchangeable implementations are provided:

* ``DynamoRepository`` - production implementation for DynamoDB.
* ``LocalRepository``  - file-backed implementation for local development
  and tests. Both expose the same interface so handlers are storage agnostic.

Table design (applicants table):
  pk = APPLICANT#<id>          sk = PROFILE
  pk = SOURCE#<response_id>    sk = IDEMPOTENCY
  pk = LIST                    sk = SUBMITTED#<iso>#<id>      (default ordering)
  pk = LIST#SCORE              sk = SCORE#<inverted>#<id>     (score ordering)
  pk = LIST#NAME               sk = NAME#<lowercase>#<id>     (name ordering)

Evaluations live in their own table with pk = APPLICANT#<id>,
sk = EVAL#<iso>#<evaluation_id>, plus an EVAL#LATEST pointer.

Audit entries:   pk = APPLICANT#<id> | AUDIT#GLOBAL, sk = AUDIT#<iso>#<audit_id>
Configuration:   pk = CONFIG, sk = <config_key>
Reports:         pk = REPORT#<id>, sk = REPORT; listing pk = REPORTS
"""

from __future__ import annotations

import base64
import json
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Settings, get_settings
from .errors import ConflictError, NotFoundError
from .logging_utils import get_logger
from .models import Applicant, AuditEntry, Evaluation, ReportRecord, iso, parse_dt, utcnow

logger = get_logger("sbg.repo")

LIST_PK = "LIST"
SCORE_PK = "LIST#SCORE"
NAME_PK = "LIST#NAME"
CONFIG_PK = "CONFIG"
REPORT_PK = "REPORTS"


@dataclass
class ApplicantFilters:
    q: str = ""
    role: str = ""
    status: str = ""
    eligibility: str = ""
    recommendation: str = ""
    review_status: str = ""
    department: str = ""
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    urgent: bool = False
    sort: str = "submitted_at"
    page_size: int = 25
    cursor: str = ""

    def normalized(self) -> "ApplicantFilters":
        self.page_size = max(1, min(int(self.page_size or 25), 100))
        self.q = (self.q or "").strip()[:120]
        return self


@dataclass
class Page:
    items: list[Any] = field(default_factory=list)
    next_cursor: Optional[str] = None
    total_scanned: int = 0


def encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:  # noqa: BLE001
        return {}


class Repository(ABC):
    @abstractmethod
    def put_applicant_if_absent(self, applicant: Applicant) -> bool: ...

    @abstractmethod
    def save_applicant(self, applicant: Applicant) -> None: ...

    @abstractmethod
    def get_applicant(self, applicant_id: str) -> Applicant: ...

    @abstractmethod
    def update_applicant(self, applicant_id: str, updates: dict[str, Any], *, actor: str = "system") -> Applicant: ...

    @abstractmethod
    def list_applicants(self, filters: ApplicantFilters) -> Page: ...

    @abstractmethod
    def save_evaluation(self, evaluation: Evaluation) -> None: ...

    @abstractmethod
    def get_latest_evaluation(self, applicant_id: str) -> Optional[Evaluation]: ...

    @abstractmethod
    def get_evaluation(self, applicant_id: str, evaluation_id: str) -> Optional[Evaluation]: ...

    @abstractmethod
    def list_evaluations(self, applicant_id: str) -> list[Evaluation]: ...

    @abstractmethod
    def add_audit(self, entry: AuditEntry) -> None: ...

    @abstractmethod
    def list_audit(self, applicant_id: str = "", limit: int = 200) -> list[AuditEntry]: ...

    @abstractmethod
    def get_config(self, key: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def put_config(self, key: str, value: dict[str, Any], *, actor: str = "system") -> dict[str, Any]: ...

    @abstractmethod
    def list_config(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def save_report(self, record: ReportRecord) -> None: ...

    @abstractmethod
    def get_report(self, report_id: str) -> ReportRecord: ...

    @abstractmethod
    def list_reports(self, limit: int = 50) -> list[ReportRecord]: ...

    @abstractmethod
    def count_by_status(self) -> dict[str, int]: ...

    @abstractmethod
    def list_ranked(self, role: str = "", limit: int = 500) -> list[Applicant]: ...

    def close(self) -> None:  # pragma: no cover - optional
        return None


# ---------------------------------------------------------------------------
# DynamoDB implementation
# ---------------------------------------------------------------------------


class DynamoRepository(Repository):
    def __init__(self, settings: Optional[Settings] = None):
        import boto3  # imported lazily so local mode does not require it

        self.settings = settings or get_settings()
        self._resource = boto3.resource("dynamodb", region_name=self.settings.region)
        self.applicants = self._resource.Table(self.settings.applicants_table)
        self.evaluations = self._resource.Table(self.settings.evaluations_table)
        self.audit = self._resource.Table(self.settings.audit_table)
        self.config = self._resource.Table(self.settings.config_table)
        self.reports = self._resource.Table(self.settings.reports_table)

    # -- applicants ---------------------------------------------------------
    def put_applicant_if_absent(self, applicant: Applicant) -> bool:
        try:
            self.applicants.put_item(
                Item=self._applicant_item(applicant),
                ConditionExpression="attribute_not_exists(pk)",
            )
        except self._resource.meta.client.exceptions.ConditionalCheckFailedException:
            return False
        self.applicants.put_item(
            Item={
                "pk": f"SOURCE#{applicant.source_response_id}",
                "sk": "IDEMPOTENCY",
                "entity": "IDEMPOTENCY",
                "applicant_id": applicant.applicant_id,
                "created_at": iso(utcnow()),
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        self._put_listings(applicant)
        return True

    def save_applicant(self, applicant: Applicant) -> None:
        applicant.updated_at = utcnow()
        self.applicants.put_item(Item=self._applicant_item(applicant))
        self._put_listings(applicant)

    def get_applicant(self, applicant_id: str) -> Applicant:
        resp = self.applicants.get_item(Key={"pk": f"APPLICANT#{applicant_id}", "sk": "PROFILE"})
        item = resp.get("Item")
        if not item:
            raise NotFoundError(f"Applicant {applicant_id} not found")
        return Applicant.from_dict(self._strip(item))

    def update_applicant(self, applicant_id: str, updates: dict[str, Any], *, actor: str = "system") -> Applicant:
        applicant = self.get_applicant(applicant_id)
        for key, value in updates.items():
            if hasattr(applicant, key):
                setattr(applicant, key, value)
        applicant.version += 1
        self.save_applicant(applicant)
        return applicant

    def _applicant_item(self, applicant: Applicant) -> dict[str, Any]:
        item = applicant.to_dict()
        item["pk"] = f"APPLICANT#{applicant.applicant_id}"
        item["sk"] = "PROFILE"
        item["entity"] = "APPLICANT"
        item["search_text"] = applicant.search_text()
        item["score_listing_sk"] = self._score_sk(applicant)
        return self._clean(item)

    def _listing_item(self, applicant: Applicant, pk: str, sk: str) -> dict[str, Any]:
        return self._clean(
            {
                "pk": pk,
                "sk": sk,
                "entity": "LISTING",
                "applicant_id": applicant.applicant_id,
                "full_name": applicant.full_name,
                "email": applicant.email,
                "usn": applicant.usn,
                "department": applicant.department,
                "year_of_study": applicant.year_of_study,
                "roles": applicant.roles,
                "submitted_at": iso(applicant.submitted_at),
                "processing_status": applicant.processing_status,
                "eligibility_status": applicant.eligibility_status,
                "recommendation": applicant.recommendation,
                "review_status": applicant.review_status,
                "total_score": str(applicant.total_score),
                "urgent_review": applicant.urgent_review,
                "search_text": applicant.search_text(),
                "rubric_version": applicant.rubric_version,
                "updated_at": iso(applicant.updated_at),
            }
        )

    def _score_sk(self, applicant: Applicant) -> str:
        inverted = max(0.0, min(100.0, 1000.0 - float(applicant.total_score or 0.0)))
        return f"SCORE#{inverted:010.2f}#{applicant.applicant_id}"

    def _put_listings(self, applicant: Applicant) -> None:
        self.applicants.put_item(Item=self._listing_item(applicant, LIST_PK, f"SUBMITTED#{iso(applicant.submitted_at)}#{applicant.applicant_id}"))
        self.applicants.put_item(Item=self._listing_item(applicant, SCORE_PK, self._score_sk(applicant)))
        self.applicants.put_item(
            Item=self._listing_item(applicant, NAME_PK, f"NAME#{applicant.full_name.lower()}#{applicant.applicant_id}")
        )

    def list_applicants(self, filters: ApplicantFilters) -> Page:
        from boto3.dynamodb.conditions import Attr

        filters = filters.normalized()
        partition, forward = {
            "score": (SCORE_PK, True),
            "name": (NAME_PK, True),
        }.get(filters.sort, (LIST_PK, False))

        expression = None

        def add(cond: Any) -> None:
            nonlocal expression
            expression = cond if expression is None else expression & cond

        if filters.q:
            add(Attr("search_text").contains(filters.q.lower()))
        if filters.role:
            add(Attr("roles").contains(filters.role))
        if filters.status:
            add(Attr("processing_status").eq(filters.status))
        if filters.eligibility:
            add(Attr("eligibility_status").eq(filters.eligibility))
        if filters.recommendation:
            add(Attr("recommendation").eq(filters.recommendation))
        if filters.review_status:
            add(Attr("review_status").eq(filters.review_status))
        if filters.department:
            add(Attr("department").eq(filters.department))
        if filters.urgent:
            add(Attr("urgent_review").eq(True))
        if filters.min_score is not None:
            add(Attr("total_score").gte(str(filters.min_score)))
        if filters.max_score is not None:
            add(Attr("total_score").lte(str(filters.max_score)))

        cursor = decode_cursor(filters.cursor)
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": partition},
            "Limit": filters.page_size,
            "ScanIndexForward": forward,
        }
        if expression is not None:
            kwargs["FilterExpression"] = expression
        if cursor.get("key"):
            kwargs["ExclusiveStartKey"] = cursor["key"]

        resp = self.applicants.query(**kwargs)
        ids = [item["applicant_id"] for item in resp.get("Items", [])]
        items = [self.get_applicant(applicant_id) for applicant_id in ids]
        next_key = resp.get("LastEvaluatedKey")
        return Page(
            items=items,
            next_cursor=encode_cursor({"key": next_key}) if next_key else None,
            total_scanned=resp.get("ScannedCount", 0),
        )

    def list_ranked(self, role: str = "", limit: int = 500) -> list[Applicant]:
        from boto3.dynamodb.conditions import Attr

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": SCORE_PK},
            "Limit": min(limit, 1000),
            "ScanIndexForward": True,
        }
        if role:
            kwargs["FilterExpression"] = Attr("roles").contains(role)
        resp = self.applicants.query(**kwargs)
        return [self.get_applicant(item["applicant_id"]) for item in resp.get("Items", [])]

    def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": LIST_PK},
            "ProjectionExpression": "processing_status, eligibility_status, recommendation, review_status",
        }
        while True:
            resp = self.applicants.query(**kwargs)
            for item in resp.get("Items", []):
                status = item.get("processing_status", "UNKNOWN")
                counts[status] = counts.get(status, 0) + 1
                rec = item.get("recommendation", "UNKNOWN")
                counts[f"REC:{rec}"] = counts.get(f"REC:{rec}", 0) + 1
                elig = item.get("eligibility_status", "UNKNOWN")
                counts[f"ELIG:{elig}"] = counts.get(f"ELIG:{elig}", 0) + 1
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return counts

    # -- evaluations --------------------------------------------------------
    def save_evaluation(self, evaluation: Evaluation) -> None:
        item = evaluation.to_dict()
        item["pk"] = f"APPLICANT#{evaluation.applicant_id}"
        item["sk"] = f"EVAL#{iso(evaluation.created_at)}#{evaluation.evaluation_id}"
        item["entity"] = "EVALUATION"
        self.evaluations.put_item(Item=self._clean(item))
        self.evaluations.put_item(
            Item=self._clean(
                {
                    "pk": f"APPLICANT#{evaluation.applicant_id}",
                    "sk": "EVAL#LATEST",
                    "entity": "EVALUATION_POINTER",
                    "evaluation_id": evaluation.evaluation_id,
                    "total_score": str(evaluation.total_score),
                    "recommendation": evaluation.recommendation,
                    "created_at": iso(evaluation.created_at),
                }
            )
        )

    def get_latest_evaluation(self, applicant_id: str) -> Optional[Evaluation]:
        pointer = self.evaluations.get_item(Key={"pk": f"APPLICANT#{applicant_id}", "sk": "EVAL#LATEST"}).get("Item")
        if not pointer:
            return None
        return self.get_evaluation(applicant_id, pointer["evaluation_id"])

    def get_evaluation(self, applicant_id: str, evaluation_id: str) -> Optional[Evaluation]:
        resp = self.evaluations.scan(
            FilterExpression="pk = :pk AND evaluation_id = :eid",
            ExpressionAttributeValues={":pk": f"APPLICANT#{applicant_id}", ":eid": evaluation_id},
            Limit=25,
        )
        items = resp.get("Items", [])
        return Evaluation.from_dict(self._strip(items[0])) if items else None

    def list_evaluations(self, applicant_id: str) -> list[Evaluation]:
        resp = self.evaluations.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"APPLICANT#{applicant_id}", ":prefix": "EVAL#"},
            ScanIndexForward=False,
            Limit=50,
        )
        out = []
        for item in resp.get("Items", []):
            if item.get("sk") == "EVAL#LATEST":
                continue
            out.append(Evaluation.from_dict(self._strip(item)))
        return out

    # -- audit --------------------------------------------------------------
    def add_audit(self, entry: AuditEntry) -> None:
        for pk in (f"APPLICANT#{entry.applicant_id}" if entry.applicant_id else "AUDIT#GLOBAL", "AUDIT#GLOBAL"):
            item = entry.to_dict()
            item["pk"] = pk
            item["sk"] = f"AUDIT#{iso(entry.timestamp)}#{entry.audit_id}"
            item["entity"] = "AUDIT"
            self.audit.put_item(Item=self._clean(item))

    def list_audit(self, applicant_id: str = "", limit: int = 200) -> list[AuditEntry]:
        pk = f"APPLICANT#{applicant_id}" if applicant_id else "AUDIT#GLOBAL"
        resp = self.audit.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": pk, ":prefix": "AUDIT#"},
            ScanIndexForward=False,
            Limit=min(limit, 500),
        )
        return [AuditEntry.from_dict(self._strip(item)) for item in resp.get("Items", [])]

    # -- config -------------------------------------------------------------
    def get_config(self, key: str) -> Optional[dict[str, Any]]:
        item = self.config.get_item(Key={"pk": CONFIG_PK, "sk": key}).get("Item")
        if not item:
            return None
        return {"key": key, "value": item.get("value"), "version": int(item.get("version", 1)), "updated_at": item.get("updated_at"), "updated_by": item.get("updated_by")}

    def put_config(self, key: str, value: dict[str, Any], *, actor: str = "system") -> dict[str, Any]:
        existing = self.get_config(key)
        version = (existing["version"] + 1) if existing else 1
        item = {
            "pk": CONFIG_PK,
            "sk": key,
            "entity": "CONFIG",
            "value": value,
            "version": version,
            "updated_at": iso(utcnow()),
            "updated_by": actor,
        }
        self.config.put_item(Item=self._clean(item))
        return {"key": key, "value": value, "version": version, "updated_at": item["updated_at"], "updated_by": actor}

    def list_config(self) -> list[dict[str, Any]]:
        resp = self.config.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": CONFIG_PK},
        )
        return [
            {"key": item["sk"], "value": item.get("value"), "version": int(item.get("version", 1)), "updated_at": item.get("updated_at"), "updated_by": item.get("updated_by")}
            for item in resp.get("Items", [])
        ]

    # -- reports ------------------------------------------------------------
    def save_report(self, record: ReportRecord) -> None:
        item = record.to_dict()
        item.update({"pk": f"REPORT#{record.report_id}", "sk": "REPORT", "entity": "REPORT"})
        self.reports.put_item(Item=self._clean(item))
        self.reports.put_item(
            Item=self._clean(
                {
                    "pk": REPORT_PK,
                    "sk": f"REPORT#{iso(record.created_at)}#{record.report_id}",
                    "entity": "REPORT_LISTING",
                    "report_id": record.report_id,
                    "kind": record.kind,
                    "status": record.status,
                    "filename": record.filename,
                    "created_by": record.created_by,
                    "created_at": iso(record.created_at),
                }
            )
        )

    def get_report(self, report_id: str) -> ReportRecord:
        item = self.reports.get_item(Key={"pk": f"REPORT#{report_id}", "sk": "REPORT"}).get("Item")
        if not item:
            raise NotFoundError(f"Report {report_id} not found")
        return ReportRecord.from_dict(self._strip(item))

    def list_reports(self, limit: int = 50) -> list[ReportRecord]:
        resp = self.reports.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": REPORT_PK, ":prefix": "REPORT#"},
            ScanIndexForward=False,
            Limit=min(limit, 200),
        )
        return [self.get_report(item["report_id"]) for item in resp.get("Items", [])]

    # -- helpers ------------------------------------------------------------
    def _clean(self, item: dict[str, Any]) -> dict[str, Any]:
        """Remove None/empty values and convert floats DynamoDB cannot store."""
        out: dict[str, Any] = {}
        for key, value in item.items():
            if value is None or value == "":
                continue
            if isinstance(value, float):
                out[key] = str(value)
            elif isinstance(value, list) and not value:
                continue
            elif isinstance(value, dict) and not value:
                continue
            else:
                out[key] = value
        return out

    def _strip(self, item: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in item.items() if k not in {"pk", "sk", "entity", "score_listing_sk", "search_text"}}


# ---------------------------------------------------------------------------
# Local file-backed implementation
# ---------------------------------------------------------------------------


class LocalRepository(Repository):
    """Simple durable JSON store used for local development and tests."""

    def __init__(self, path: Optional[str] = None):
        self.settings = get_settings()
        base = Path(path or self.settings.local_store_path)
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "store.json"
        self._lock = threading.RLock()
        self.data: dict[str, Any] = {"applicants": {}, "evaluations": {}, "audit": [], "config": {}, "reports": {}}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                logger.error("Local store is corrupt; starting fresh")

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- applicants ---------------------------------------------------------
    def put_applicant_if_absent(self, applicant: Applicant) -> bool:
        with self._lock:
            if applicant.applicant_id in self.data["applicants"]:
                return False
            for existing in self.data["applicants"].values():
                if existing.get("source_response_id") == applicant.source_response_id:
                    return False
            self.data["applicants"][applicant.applicant_id] = applicant.to_dict()
            self._flush()
            return True

    def save_applicant(self, applicant: Applicant) -> None:
        with self._lock:
            applicant.updated_at = utcnow()
            self.data["applicants"][applicant.applicant_id] = applicant.to_dict()
            self._flush()

    def get_applicant(self, applicant_id: str) -> Applicant:
        raw = self.data["applicants"].get(applicant_id)
        if not raw:
            raise NotFoundError(f"Applicant {applicant_id} not found")
        return Applicant.from_dict(raw)

    def update_applicant(self, applicant_id: str, updates: dict[str, Any], *, actor: str = "system") -> Applicant:
        with self._lock:
            applicant = self.get_applicant(applicant_id)
            for key, value in updates.items():
                if hasattr(applicant, key):
                    setattr(applicant, key, value)
            applicant.version += 1
            self.save_applicant(applicant)
            return applicant

    def list_applicants(self, filters: ApplicantFilters) -> Page:
        filters = filters.normalized()
        items = [Applicant.from_dict(raw) for raw in self.data["applicants"].values()]

        def matches(a: Applicant) -> bool:
            if filters.q:
                if filters.q.lower() not in a.search_text():
                    return False
            if filters.role and filters.role not in a.roles:
                return False
            if filters.status and a.processing_status != filters.status:
                return False
            if filters.eligibility and a.eligibility_status != filters.eligibility:
                return False
            if filters.recommendation and a.recommendation != filters.recommendation:
                return False
            if filters.review_status and a.review_status != filters.review_status:
                return False
            if filters.department and a.department != filters.department:
                return False
            if filters.urgent and not a.urgent_review:
                return False
            if filters.min_score is not None and a.total_score < filters.min_score:
                return False
            if filters.max_score is not None and a.total_score > filters.max_score:
                return False
            return True

        items = [a for a in items if matches(a)]
        if filters.sort == "score":
            items.sort(key=lambda a: (-a.total_score, a.full_name.lower()))
        elif filters.sort == "name":
            items.sort(key=lambda a: a.full_name.lower())
        else:
            items.sort(key=lambda a: a.submitted_at, reverse=True)

        offset = int(decode_cursor(filters.cursor).get("offset", 0))
        window = items[offset : offset + filters.page_size]
        next_cursor = None
        if offset + filters.page_size < len(items):
            next_cursor = encode_cursor({"offset": offset + filters.page_size})
        return Page(items=window, next_cursor=next_cursor, total_scanned=len(items))

    def list_ranked(self, role: str = "", limit: int = 500) -> list[Applicant]:
        items = [Applicant.from_dict(raw) for raw in self.data["applicants"].values()]
        if role:
            items = [a for a in items if role in a.roles]
        items.sort(key=lambda a: (-a.total_score, a.submitted_at))
        return items[:limit]

    def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for raw in self.data["applicants"].values():
            status = raw.get("processing_status", "UNKNOWN")
            counts[status] = counts.get(status, 0) + 1
            rec = raw.get("recommendation", "UNKNOWN")
            counts[f"REC:{rec}"] = counts.get(f"REC:{rec}", 0) + 1
            elig = raw.get("eligibility_status", "UNKNOWN")
            counts[f"ELIG:{elig}"] = counts.get(f"ELIG:{elig}", 0) + 1
        return counts

    # -- evaluations --------------------------------------------------------
    def save_evaluation(self, evaluation: Evaluation) -> None:
        with self._lock:
            bucket = self.data["evaluations"].setdefault(evaluation.applicant_id, {})
            bucket[evaluation.evaluation_id] = evaluation.to_dict()
            self._flush()

    def get_latest_evaluation(self, applicant_id: str) -> Optional[Evaluation]:
        bucket = self.data["evaluations"].get(applicant_id) or {}
        if not bucket:
            return None
        latest = max(bucket.values(), key=lambda e: str(e.get("created_at", "")))
        return Evaluation.from_dict(latest)

    def get_evaluation(self, applicant_id: str, evaluation_id: str) -> Optional[Evaluation]:
        raw = (self.data["evaluations"].get(applicant_id) or {}).get(evaluation_id)
        return Evaluation.from_dict(raw) if raw else None

    def list_evaluations(self, applicant_id: str) -> list[Evaluation]:
        bucket = self.data["evaluations"].get(applicant_id) or {}
        evals = [Evaluation.from_dict(raw) for raw in bucket.values()]
        evals.sort(key=lambda e: e.created_at, reverse=True)
        return evals

    # -- audit --------------------------------------------------------------
    def add_audit(self, entry: AuditEntry) -> None:
        with self._lock:
            self.data["audit"].append(entry.to_dict())
            self.data["audit"] = self.data["audit"][-5000:]
            self._flush()

    def list_audit(self, applicant_id: str = "", limit: int = 200) -> list[AuditEntry]:
        rows = [AuditEntry.from_dict(raw) for raw in self.data["audit"]]
        if applicant_id:
            rows = [r for r in rows if r.applicant_id == applicant_id]
        rows.sort(key=lambda r: r.timestamp, reverse=True)
        return rows[:limit]

    # -- config -------------------------------------------------------------
    def get_config(self, key: str) -> Optional[dict[str, Any]]:
        raw = self.data["config"].get(key)
        return json.loads(json.dumps(raw)) if raw else None

    def put_config(self, key: str, value: dict[str, Any], *, actor: str = "system") -> dict[str, Any]:
        with self._lock:
            existing = self.data["config"].get(key)
            version = int(existing["version"]) + 1 if existing else 1
            record = {
                "key": key,
                "value": value,
                "version": version,
                "updated_at": iso(utcnow()),
                "updated_by": actor,
            }
            self.data["config"][key] = record
            self._flush()
            return record

    def list_config(self) -> list[dict[str, Any]]:
        return [json.loads(json.dumps(v)) for v in self.data["config"].values()]

    # -- reports ------------------------------------------------------------
    def save_report(self, record: ReportRecord) -> None:
        with self._lock:
            self.data["reports"][record.report_id] = record.to_dict()
            self._flush()

    def get_report(self, report_id: str) -> ReportRecord:
        raw = self.data["reports"].get(report_id)
        if not raw:
            raise NotFoundError(f"Report {report_id} not found")
        return ReportRecord.from_dict(raw)

    def list_reports(self, limit: int = 50) -> list[ReportRecord]:
        rows = [ReportRecord.from_dict(raw) for raw in self.data["reports"].values()]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]


_repository: Optional[Repository] = None


def get_repository(settings: Optional[Settings] = None) -> Repository:
    global _repository
    if _repository is not None:
        return _repository
    settings = settings or get_settings()
    if settings.is_local:
        _repository = LocalRepository()
    else:
        _repository = DynamoRepository(settings)
    return _repository


def reset_repository(repo: Optional[Repository] = None) -> None:
    global _repository
    _repository = repo
