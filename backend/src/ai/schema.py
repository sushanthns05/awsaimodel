"""Structured JSON parsing and validation for AI responses."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class AIResponseError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


def parse_json_object(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise AIResponseError("AI returned an empty response")
    cleaned = _FENCE.sub("", text.strip()).strip()
    if cleaned.startswith("{"):
        candidate = cleaned
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise AIResponseError("AI response did not contain a JSON object")
        candidate = cleaned[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AIResponseError(f"AI returned invalid JSON: {exc.msg} at position {exc.pos}") from exc
    if not isinstance(parsed, dict):
        raise AIResponseError("AI response must be a JSON object")
    return parsed


def _require_string(obj: dict[str, Any], key: str, errors: list[str], *, max_len: int = 8000) -> str:
    value = obj.get(key)
    if value is None:
        errors.append(f"missing field '{key}'")
        return ""
    if not isinstance(value, str):
        errors.append(f"field '{key}' must be a string")
        return ""
    return value.strip()[:max_len]


def _string_list(obj: dict[str, Any], key: str, errors: list[str], *, max_items: int = 30) -> list[str]:
    value = obj.get(key, [])
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        errors.append(f"field '{key}' must be a list of strings")
        return []
    out: list[str] = []
    for item in value[:max_items]:
        if isinstance(item, (dict, list)):
            errors.append(f"field '{key}' must contain only strings")
            continue
        text = str(item).strip()
        if text:
            out.append(text[:500])
    return out


def _dict_list(obj: dict[str, Any], key: str, errors: list[str], *, max_items: int = 20) -> list[dict[str, Any]]:
    value = obj.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"field '{key}' must be a list of objects")
        return []
    out = [item for item in value[:max_items] if isinstance(item, dict)]
    if len(out) != len(value[:max_items]):
        errors.append(f"field '{key}' contained non-object entries")
    return out


def validate_ai_result(
    data: dict[str, Any],
    rubric: dict[str, Any],
    expected_roles: list[str],
) -> dict[str, Any]:
    errors: list[str] = []

    summary = _require_string(data, "candidate_summary", errors)
    confidence = str(data.get("confidence", "medium")).lower()
    if confidence not in ("high", "medium", "low"):
        errors.append("field 'confidence' must be high, medium or low")
        confidence = "medium"

    criteria_ids = {str(c["id"]) for c in rubric.get("criteria", [])}
    criteria_raw = data.get("criteria")
    if not isinstance(criteria_raw, list) or not criteria_raw:
        errors.append("field 'criteria' must be a non-empty list")
        criteria_raw = []

    seen: set[str] = set()
    criteria: list[dict[str, Any]] = []
    for entry in criteria_raw:
        if not isinstance(entry, dict):
            errors.append("criteria entries must be objects")
            continue
        cid = str(entry.get("id", "")).strip()
        if cid not in criteria_ids:
            errors.append(f"unknown criterion id '{cid}'")
            continue
        if cid in seen:
            errors.append(f"duplicate criterion id '{cid}'")
            continue
        seen.add(cid)
        fraction = entry.get("score_fraction")
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
            errors.append(f"criterion '{cid}' score_fraction must be a number")
            continue
        if not 0 <= float(fraction) <= 1:
            errors.append(f"criterion '{cid}' score_fraction must be between 0 and 1")
            continue
        evidence = entry.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, list):
            errors.append(f"criterion '{cid}' evidence must be a list")
            evidence = []
        evidence = [str(e).strip()[:600] for e in evidence if str(e).strip()]
        if float(fraction) > 0 and not evidence:
            errors.append(f"criterion '{cid}' has marks but no evidence")
            continue
        criteria.append(
            {
                "id": cid,
                "score_fraction": round(float(fraction), 4),
                "evidence": evidence[:8],
                "reasoning": str(entry.get("reasoning") or "")[:1500],
            }
        )

    missing = criteria_ids - seen
    if missing:
        errors.append("missing criteria: " + ", ".join(sorted(missing)))

    role_knowledge_raw = data.get("role_knowledge")
    role_knowledge: dict[str, dict[str, Any]] = {}
    if not isinstance(role_knowledge_raw, dict):
        errors.append("field 'role_knowledge' must be an object keyed by role id")
        role_knowledge_raw = {}
    for role_id, payload in role_knowledge_raw.items():
        if str(role_id) not in expected_roles:
            continue
        if not isinstance(payload, dict):
            errors.append(f"role_knowledge['{role_id}'] must be an object")
            continue
        fraction = payload.get("score_fraction")
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= float(fraction) <= 1:
            errors.append(f"role_knowledge['{role_id}'] score_fraction invalid")
            continue
        evidence = payload.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = [str(e).strip()[:600] for e in evidence if str(e).strip()] if isinstance(evidence, list) else []
        if float(fraction) > 0 and not evidence:
            errors.append(f"role_knowledge['{role_id}'] has marks but no evidence")
            continue
        role_knowledge[str(role_id)] = {
            "score_fraction": round(float(fraction), 4),
            "evidence": evidence[:8],
            "reasoning": str(payload.get("reasoning") or "")[:1000],
        }
    for role_id in expected_roles:
        if role_id not in role_knowledge:
            errors.append(f"role_knowledge missing role '{role_id}'")

    role_fit_raw = data.get("role_fit") or {}
    role_fit: dict[str, dict[str, str]] = {}
    if isinstance(role_fit_raw, dict):
        for role_id, payload in role_fit_raw.items():
            if str(role_id) in expected_roles and isinstance(payload, dict):
                fit = str(payload.get("fit") or "").lower()
                role_fit[str(role_id)] = {
                    "fit": fit if fit in ("strong", "moderate", "limited") else "moderate",
                    "rationale": str(payload.get("rationale") or "")[:1200],
                }

    questions = _dict_list(data, "interview_questions", errors, max_items=15)
    normalised_questions = []
    for q in questions:
        question = str(q.get("question") or "").strip()
        if not question:
            continue
        role = str(q.get("role") or (expected_roles[0] if expected_roles else "other"))
        if role not in expected_roles:
            role = expected_roles[0] if expected_roles else "other"
        normalised_questions.append({"role": role, "question": question[:600], "why": str(q.get("why") or "")[:400]})

    if errors:
        raise AIResponseError("AI response failed validation", errors)

    return {
        "candidate_summary": summary,
        "technical_skills": _string_list(data, "technical_skills", errors, max_items=40),
        "nontechnical_skills": _string_list(data, "nontechnical_skills", errors, max_items=40),
        "projects": _dict_list(data, "projects", errors, max_items=15),
        "experience": _dict_list(data, "experience", errors, max_items=15),
        "certifications": _string_list(data, "certifications", errors, max_items=20),
        "leadership_evidence": _string_list(data, "leadership_evidence", errors, max_items=10),
        "communication_evidence": _string_list(data, "communication_evidence", errors, max_items=10),
        "strengths": _string_list(data, "strengths", errors, max_items=10),
        "weaknesses": _string_list(data, "weaknesses", errors, max_items=10),
        "missing_information": _string_list(data, "missing_information", errors, max_items=15),
        "inconsistencies": _string_list(data, "inconsistencies", errors, max_items=10),
        "uncertain_findings": _string_list(data, "uncertain_findings", errors, max_items=10),
        "criteria": criteria,
        "role_knowledge": role_knowledge,
        "role_fit": role_fit,
        "interview_questions": normalised_questions,
        "confidence": confidence,
    }
