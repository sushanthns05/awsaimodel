"""Deterministic eligibility evaluation.

Rules are configuration driven and evaluated in Python only. A failed
mandatory rule never rejects a candidate automatically; it flags the
applicant with the exact reason for human verification.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..common.models import (
    ELIGIBILITY_FAIL,
    ELIGIBILITY_PASS,
    ELIGIBILITY_UNKNOWN,
    Applicant,
    EligibilityResult,
)

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def coerce_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value))
    return float(match.group()) if match else None


def coerce_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "yes", "y", "1", "i agree", "agreed", "consent"):
        return True
    if text in ("false", "no", "n", "0"):
        return False
    return None


def resolve_field(applicant: Applicant, path: str) -> Any:
    """Resolve ``responses.foo``, ``personal.email`` or a direct attribute."""
    if not path:
        return None
    parts = path.split(".")
    if parts[0] == "responses":
        value: Any = applicant.responses
        for part in parts[1:]:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value
    if parts[0] == "personal":
        return getattr(applicant, parts[1], None) if len(parts) > 1 else None
    if hasattr(applicant, parts[0]):
        return getattr(applicant, parts[0])
    return None


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def evaluate_rule(applicant: Applicant, rule: dict[str, Any]) -> EligibilityResult:
    rule_id = str(rule["id"])
    label = str(rule.get("label") or rule_id)
    mandatory = bool(rule.get("mandatory", True))
    rule_type = str(rule.get("type", "required"))
    value = resolve_field(applicant, str(rule.get("field", "")))
    message = str(rule.get("message") or label)

    def result(status: str, detail: str = "", observed: Any = "") -> EligibilityResult:
        return EligibilityResult(
            rule_id=rule_id,
            label=label,
            status=status,
            mandatory=mandatory,
            detail=detail or (message if status == ELIGIBILITY_FAIL else ""),
            observed=str(observed)[:300] if observed is not None else "",
        )

    if rule_type == "required":
        if _is_empty(value):
            return result(ELIGIBILITY_FAIL, message)
        return result(ELIGIBILITY_PASS, "Provided", value)

    if rule_type == "pattern":
        if _is_empty(value):
            return result(ELIGIBILITY_UNKNOWN, "Value not provided; cannot verify format.")
        if re.match(str(rule.get("pattern", "")), str(value).strip()):
            return result(ELIGIBILITY_PASS, "Format valid", value)
        return result(ELIGIBILITY_FAIL, message, value)

    if rule_type in ("min_number", "max_number"):
        number = coerce_number(value)
        if number is None:
            return result(ELIGIBILITY_UNKNOWN, "Numeric value not provided; verify manually.")
        threshold = float(rule.get("value", 0))
        if rule_type == "min_number" and number < threshold:
            return result(ELIGIBILITY_FAIL, message, number)
        if rule_type == "max_number" and number > threshold:
            return result(ELIGIBILITY_FAIL, message, number)
        return result(ELIGIBILITY_PASS, f"Observed {number:g}", number)

    if rule_type == "one_of":
        allowed = [str(v).strip().lower() for v in rule.get("values", [])]
        if _is_empty(value):
            return result(ELIGIBILITY_UNKNOWN, "Value not provided; verify manually.")
        values = value if isinstance(value, (list, tuple)) else [value]
        if any(str(v).strip().lower() in allowed for v in values):
            return result(ELIGIBILITY_PASS, "Allowed value", value)
        return result(ELIGIBILITY_FAIL, message, value)

    if rule_type == "contains":
        if _is_empty(value):
            return result(ELIGIBILITY_UNKNOWN, "Value not provided; verify manually.")
        needle = str(rule.get("value", "")).strip().lower()
        haystack = " ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
        if needle and needle in haystack.lower():
            return result(ELIGIBILITY_PASS, "Required value present", value)
        return result(ELIGIBILITY_FAIL, message, value)

    if rule_type == "boolean_true":
        flag = coerce_bool(value)
        if flag is None:
            return result(ELIGIBILITY_UNKNOWN, "Consent/acknowledgement not recorded.")
        return result(ELIGIBILITY_PASS, "Acknowledged") if flag else result(ELIGIBILITY_FAIL, message, flag)

    return result(ELIGIBILITY_UNKNOWN, f"Unsupported rule type '{rule_type}'")


def evaluate_eligibility(applicant: Applicant, config: dict[str, Any]) -> list[EligibilityResult]:
    rules = config.get("rules") or []
    return [evaluate_rule(applicant, rule) for rule in rules]


def summarise_eligibility(results: list[EligibilityResult]) -> tuple[str, list[str]]:
    failures = [r.detail or r.label for r in results if r.mandatory and r.status == ELIGIBILITY_FAIL]
    if failures:
        return ELIGIBILITY_FAIL, failures
    unknowns = [r for r in results if r.mandatory and r.status == ELIGIBILITY_UNKNOWN]
    if unknowns:
        return ELIGIBILITY_UNKNOWN, [f"{r.label}: {r.detail or 'not verified'}" for r in unknowns]
    return ELIGIBILITY_PASS, []


REQUIRED_APPLICATION_FIELDS = [
    ("full_name", "Full name"),
    ("email", "Email"),
    ("usn", "USN"),
    ("department", "Department"),
    ("year_of_study", "Year of study"),
]


def find_missing_required_fields(applicant: Applicant) -> list[str]:
    missing = [label for attr, label in REQUIRED_APPLICATION_FIELDS if _is_empty(getattr(applicant, attr, ""))]
    if not applicant.roles:
        missing.append("Role preference")
    if _is_empty(resolve_field(applicant, "responses.availability")):
        missing.append("Availability")
    if _is_empty(applicant.documents):
        missing.append("Resume document")
    return missing
