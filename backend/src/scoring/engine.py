"""Deterministic scoring engine.

The AI proposes an evidence-backed fraction (0..1) for each rubric
criterion. This module is the only place where points are calculated.
Invalid AI values are never silently accepted and missing evidence is never
replaced with assumed marks.
"""

from __future__ import annotations

from typing import Any, Optional

from ..common.models import (
    ELIGIBILITY_FAIL,
    ELIGIBILITY_PASS,
    ELIGIBILITY_UNKNOWN,
    Applicant,
    CriterionScore,
    Evaluation,
    EligibilityResult,
    iso,
    new_id,
    utcnow,
)
from .eligibility import evaluate_eligibility, find_missing_required_fields, summarise_eligibility


class ScoringError(ValueError):
    pass


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def role_map(roles_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(role["id"]): role for role in roles_config.get("roles", [])}


def normalise_role_ids(applicant_roles: list[str], roles_config: dict[str, Any]) -> list[str]:
    known = role_map(roles_config)
    resolved = [role for role in applicant_roles if role in known]
    if not resolved:
        default = roles_config.get("default_role") or next(iter(known), "other")
        resolved = [default]
    return resolved


def resolve_criteria(rubric: dict[str, Any], role_id: str, roles_config: dict[str, Any]) -> list[dict[str, Any]]:
    role = role_map(roles_config).get(role_id, {})
    weights = role.get("weights") or {}
    criteria: list[dict[str, Any]] = []
    for criterion in rubric.get("criteria", []):
        cid = str(criterion["id"])
        max_score = _as_float(weights.get(cid, criterion.get("max_score")))
        if max_score is None:
            max_score = float(criterion.get("max_score", 0))
        criteria.append({**criterion, "id": cid, "max_score": max_score})
    return criteria


def recommendation_for(score: float, rubric: dict[str, Any]) -> str:
    thresholds = sorted(
        rubric.get("recommendation_thresholds", []),
        key=lambda item: float(item.get("min_score", 0)),
        reverse=True,
    )
    for band in thresholds:
        if score >= float(band.get("min_score", 0)):
            return str(band.get("recommendation", "MANUAL_REVIEW"))
    return "MANUAL_REVIEW"


def _extract_fractions(
    ai_result: dict[str, Any],
    rubric: dict[str, Any],
    primary_role: str,
) -> tuple[dict[str, float], dict[str, dict[str, float]], dict[str, tuple[list[str], str]], list[str]]:
    """Return fractions, per-role role-knowledge fractions, evidence and errors."""
    entries = ai_result.get("criteria") or []
    if not isinstance(entries, list):
        return {}, {}, {}, ["AI response 'criteria' must be a list"]

    by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            errors.append("AI returned a criterion without an id")
            continue
        cid = str(entry["id"])
        if cid in by_id:
            errors.append(f"Duplicate criterion '{cid}' in AI response")
            continue
        by_id[cid] = entry

    known_ids = {str(c["id"]) for c in rubric.get("criteria", [])}
    for cid in by_id:
        if cid not in known_ids:
            errors.append(f"AI returned unknown criterion '{cid}'")

    fractions: dict[str, float] = {}
    evidence: dict[str, tuple[list[str], str]] = {}
    for criterion in rubric.get("criteria", []):
        cid = str(criterion["id"])
        entry = by_id.get(cid)
        if not entry:
            errors.append(f"Missing AI evaluation for criterion '{cid}'")
            continue
        fraction = _as_float(entry.get("score_fraction"))
        if fraction is None:
            errors.append(f"Criterion '{cid}' has a non-numeric score_fraction")
            continue
        if fraction < 0 or fraction > 1:
            errors.append(f"Criterion '{cid}' score_fraction {fraction} is outside 0..1")
            continue
        quotes = entry.get("evidence") or []
        if not isinstance(quotes, list):
            quotes = [str(quotes)]
        quotes = [str(q).strip()[:600] for q in quotes if str(q).strip()]
        if fraction > 0 and not quotes:
            errors.append(f"Criterion '{cid}' has marks but no evidence")
            continue
        fractions[cid] = fraction
        evidence[cid] = (quotes, str(entry.get("reasoning") or "")[:1500])

    role_knowledge: dict[str, dict[str, float]] = {}
    raw_role_knowledge = ai_result.get("role_knowledge") or {}
    if isinstance(raw_role_knowledge, dict):
        for role_id, payload in raw_role_knowledge.items():
            if not isinstance(payload, dict):
                continue
            fraction = _as_float(payload.get("score_fraction"))
            if fraction is None or fraction < 0 or fraction > 1:
                errors.append(f"Role knowledge for '{role_id}' has an invalid score_fraction")
                continue
            quotes = payload.get("evidence") or []
            if not isinstance(quotes, list):
                quotes = [str(quotes)]
            quotes = [str(q)[:600] for q in quotes if str(q).strip()]
            if fraction > 0 and not quotes:
                errors.append(f"Role knowledge for '{role_id}' has marks but no evidence")
                continue
            role_knowledge[str(role_id)] = {
                "fraction": fraction,
                "quotes": [str(q)[:600] for q in quotes if str(q).strip()],
                "reasoning": str(payload.get("reasoning") or "")[:1000],
            }
    return fractions, role_knowledge, evidence, errors


def build_evaluation(
    applicant: Applicant,
    ai_result: dict[str, Any],
    rubric: dict[str, Any],
    roles_config: dict[str, Any],
    eligibility_cfg: dict[str, Any],
    *,
    model_metadata: Optional[dict[str, Any]] = None,
    prompt_version: str = "",
    document_coverage: Optional[dict[str, Any]] = None,
) -> Evaluation:
    policy = str(rubric.get("invalid_response_policy", "flag_with_zero"))
    applicant_roles = normalise_role_ids(applicant.roles, roles_config)
    primary_role = applicant_roles[0]
    criteria_cfg = resolve_criteria(rubric, primary_role, roles_config)
    fractions, role_knowledge, evidence_map, errors = _extract_fractions(ai_result, rubric, primary_role)

    if errors and policy == "reject":
        raise ScoringError("AI response failed validation: " + "; ".join(errors[:8]))

    criteria: list[CriterionScore] = []
    total = 0.0
    for cfg in criteria_cfg:
        cid = cfg["id"]
        max_score = float(cfg["max_score"])
        fraction = fractions.get(cid)
        quotes, reasoning = evidence_map.get(cid, ([], ""))
        if cid == "role_knowledge" and primary_role in role_knowledge:
            fraction = role_knowledge[primary_role]["fraction"]
            quotes = role_knowledge[primary_role]["quotes"]
            reasoning = role_knowledge[primary_role]["reasoning"]
        if fraction is None:
            criteria.append(
                CriterionScore(
                    criterion_id=cid,
                    name=str(cfg.get("name", cid)),
                    max_score=max_score,
                    suggested_score=None,
                    final_score=0.0,
                    evidence=quotes,
                    reasoning=reasoning,
                    validated=False,
                    validation_error="No valid AI score; marked for human review, no marks assigned.",
                )
            )
            continue
        final_score = round(fraction * max_score, 2)
        if final_score > max_score:
            final_score = max_score
        total += final_score
        criteria.append(
            CriterionScore(
                criterion_id=cid,
                name=str(cfg.get("name", cid)),
                max_score=max_score,
                suggested_score=round(fraction, 4),
                final_score=final_score,
                evidence=quotes,
                reasoning=reasoning,
                validated=True,
            )
        )

    total = round(total, 2)
    role_scores: dict[str, float] = {}
    for role_id in applicant_roles:
        role_total = 0.0
        for cfg in resolve_criteria(rubric, role_id, roles_config):
            cid = cfg["id"]
            if cid == "role_knowledge" and role_id in role_knowledge:
                fraction = role_knowledge[role_id]["fraction"]
            else:
                fraction = fractions.get(cid, 0.0)
            role_total += fraction * float(cfg["max_score"])
        role_scores[role_id] = round(min(100.0, role_total), 2)

    eligibility = evaluate_eligibility(applicant, eligibility_cfg)
    eligibility_status, eligibility_notes = summarise_eligibility(eligibility)
    missing_fields = find_missing_required_fields(applicant)

    recommendation = recommendation_for(total, rubric)
    if eligibility_status == ELIGIBILITY_FAIL:
        recommendation = "ELIGIBILITY_REVIEW"
    if errors or missing_fields:
        # An incomplete or unvalidated evaluation must reach a human.
        recommendation = "NEEDS_REVIEW"
    application_complete = not missing_fields

    evaluation = Evaluation(
        applicant_id=applicant.applicant_id,
        evaluation_id=new_id("eval"),
        rubric_version=str(rubric.get("version", "1.0.0")),
        created_at=utcnow(),
        criteria=criteria,
        total_score=total,
        max_score=float(rubric.get("total_points", 100)),
        score_complete=not errors,
        ai_suggested_total=total,
        recommendation=recommendation,
        eligibility=eligibility,
        eligibility_status=eligibility_status,
        eligibility_failures=eligibility_notes,
        summary=str(ai_result.get("candidate_summary") or "")[:4000],
        strengths=[str(x)[:500] for x in (ai_result.get("strengths") or [])][:10],
        weaknesses=[str(x)[:500] for x in (ai_result.get("weaknesses") or [])][:10],
        missing_information=[str(x)[:500] for x in (ai_result.get("missing_information") or [])][:15]
        + [f"Application field missing: {f}" for f in missing_fields],
        inconsistencies=[str(x)[:500] for x in (ai_result.get("inconsistencies") or [])][:10],
        uncertain_findings=[str(x)[:500] for x in (ai_result.get("uncertain_findings") or [])][:10],
        technical_skills=[str(x)[:120] for x in (ai_result.get("technical_skills") or [])][:40],
        nontechnical_skills=[str(x)[:120] for x in (ai_result.get("nontechnical_skills") or [])][:40],
        projects=[p for p in (ai_result.get("projects") or []) if isinstance(p, dict)][:15],
        certifications=[str(x)[:200] for x in (ai_result.get("certifications") or [])][:20],
        experience=[p for p in (ai_result.get("experience") or []) if isinstance(p, dict)][:15],
        leadership_evidence=[str(x)[:500] for x in (ai_result.get("leadership_evidence") or [])][:10],
        communication_evidence=[str(x)[:500] for x in (ai_result.get("communication_evidence") or [])][:10],
        interview_questions=[q for q in (ai_result.get("interview_questions") or []) if isinstance(q, dict)][:15],
        role_evaluations=_role_evaluations(ai_result, applicant_roles, role_scores),
        confidence=str(ai_result.get("confidence") or "medium").lower(),
        model_metadata=model_metadata or {},
        validation_errors=errors,
        prompt_version=prompt_version,
        document_coverage=document_coverage or {},
    )
    evaluation.eligibility_status = eligibility_status
    return evaluation


def _role_evaluations(
    ai_result: dict[str, Any], applicant_roles: list[str], role_scores: dict[str, float]
) -> list[dict[str, Any]]:
    raw = ai_result.get("role_fit") or {}
    out: list[dict[str, Any]] = []
    for role_id in applicant_roles:
        payload = raw.get(role_id) if isinstance(raw, dict) else None
        fit = payload.get("fit") if isinstance(payload, dict) else ""
        rationale = payload.get("rationale") if isinstance(payload, dict) else ""
        out.append(
            {
                "role_id": role_id,
                "score": role_scores.get(role_id, 0.0),
                "fit": str(fit or "unrated")[:40],
                "rationale": str(rationale or "")[:1500],
            }
        )
    return out


def apply_manual_scores(
    evaluation: Evaluation,
    manual_scores: dict[str, float],
    *,
    reviewer: str,
    reason: str,
    rubric: dict[str, Any],
) -> Evaluation:
    by_id = {c.criterion_id: c for c in evaluation.criteria}
    for cid, value in manual_scores.items():
        criterion = by_id.get(cid)
        if not criterion:
            raise ScoringError(f"Unknown criterion '{cid}'")
        score = _as_float(value)
        if score is None or score < 0 or score > criterion.max_score:
            raise ScoringError(f"Score for '{cid}' must be between 0 and {criterion.max_score}")
        criterion.final_score = round(score, 2)
        criterion.validated = True
        criterion.validation_error = ""

    total = round(sum(c.final_score for c in evaluation.criteria), 2)
    evaluation.total_score = total
    evaluation.recommendation = recommendation_for(total, rubric)
    if evaluation.eligibility_status == ELIGIBILITY_FAIL:
        evaluation.recommendation = "ELIGIBILITY_REVIEW"
    evaluation.score_complete = all(c.validated for c in evaluation.criteria)
    evaluation.review_status = "MANUAL_REVIEW"
    evaluation.human_override = {
        "reviewer": reviewer,
        "reason": reason,
        "scores": {k: float(v) for k, v in manual_scores.items()},
        "at": iso(utcnow()),
        "total_before": evaluation.ai_suggested_total,
    }
    evaluation.version += 1
    return evaluation


def score_distribution(values: list[float], rubric: dict[str, Any]) -> list[dict[str, Any]]:
    bands = rubric.get("score_bands") or []
    out = []
    for band in bands:
        low = float(band.get("min", 0))
        high = float(band.get("max", 100))
        count = sum(1 for v in values if low <= v <= high)
        out.append({"label": band.get("label", f"{low}-{high}"), "min": low, "max": high, "count": count})
    return out
