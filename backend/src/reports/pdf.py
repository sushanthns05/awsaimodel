"""PDF report generation with ReportLab."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..common.models import Applicant, Evaluation
from .data import ReportData, ReportRow, manual_review_rows, role_shortlist, shortlisted_rows, summary_stats

NAVY = colors.HexColor("#0B1F3A")
ORANGE = colors.HexColor("#FF9900")
LIGHT = colors.HexColor("#F4F7FB")
GREY = colors.HexColor("#556070")
RED = colors.HexColor("#B42318")
GREEN = colors.HexColor("#067647")


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY, alignment=TA_LEFT, spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=10, leading=14, textColor=GREY, spaceAfter=14),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NAVY, spaceBefore=10, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=13, textColor=colors.HexColor("#1F2937")),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=11, textColor=GREY),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=10),
        "cellb": ParagraphStyle("cellb", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
        "center": ParagraphStyle("center", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12, alignment=TA_CENTER),
    }


def _table(headers: list[str], rows: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[Paragraph(_esc(h), styles["cellb"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(_esc(v), styles["cell"]) for v in row])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8DEE9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _footer(org: dict[str, Any], cycle: str, rubric_version: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D8DEE9"))
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 10 * mm, f"{org.get('name', 'AWS Student Builder Group')} · {cycle} · Rubric v{rubric_version}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _cover(data: ReportData, styles: dict[str, ParagraphStyle], title: str, subtitle: str) -> list[Any]:
    org = data.organization or {}
    cycle = org.get("cycle", "2026-27")
    story: list[Any] = [
        Spacer(1, 22 * mm),
        Paragraph("AWS STUDENT BUILDER GROUP", ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=11, textColor=ORANGE, spaceAfter=6)),
        Paragraph(_esc(title), styles["title"]),
        Paragraph(
            _esc(
                f"{org.get('name', 'AWS Student Builder Group')} · {org.get('institution', 'SJB Institute of Technology')} · "
                f"Recruitment Cycle {cycle}"
            ),
            styles["subtitle"],
        ),
        Spacer(1, 4 * mm),
        Table(
            [
                [Paragraph("Generated (UTC)", styles["cell"]), Paragraph(_esc(data.generated_at.strftime("%Y-%m-%d %H:%M")), styles["cell"])],
                [Paragraph("Rubric version", styles["cell"]), Paragraph(_esc(data.rubric_version), styles["cell"])],
                [Paragraph("Applicants included", styles["cell"]), Paragraph(str(data.total), styles["cell"])],
                [Paragraph("Report type", styles["cell"]), Paragraph(_esc(subtitle), styles["cell"])],
            ],
            colWidths=[45 * mm, 120 * mm],
            style=TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8DEE9")),
                    ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        ),
        Spacer(1, 12 * mm),
        Paragraph(
            "This report supports human recruitment decisions. AI-generated assessments are recommendations only; "
            "every shortlist decision must be confirmed by an authorised administrator. Evidence quotes are taken from "
            "applicant-supplied documents and may contain inaccuracies.",
            styles["small"],
        ),
    ]
    return story


def _summary_section(data: ReportData, styles: dict[str, ParagraphStyle]) -> list[Any]:
    stats = summary_stats(data.rows)
    story: list[Any] = [Paragraph("Executive summary", styles["h1"])]
    pairs = [
        ("Total applications", stats["total"]),
        ("Processed", stats["processed"]),
        ("Pending", stats["pending"]),
        ("Failed", stats["failed"]),
        ("Eligible", stats["eligible"]),
        ("Ineligible flags", stats["ineligible"]),
        ("Manual review", stats["needs_review"]),
        ("Approved for interview", stats["shortlisted"]),
        ("Average score", stats["average_score"]),
    ]
    rows = [[pairs[i][0], pairs[i][1], pairs[i + 1][0], pairs[i + 1][1]] for i in range(0, len(pairs) - 1, 2)]
    if len(pairs) % 2:
        rows.append([pairs[-1][0], pairs[-1][1], "", ""])
    table = Table(
        [[Paragraph(_esc(c), styles["cell"]) for c in row] for row in rows],
        colWidths=[45 * mm, 30 * mm, 45 * mm, 30 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8DEE9")),
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("BACKGROUND", (2, 0), (2, -1), LIGHT),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [table, Spacer(1, 6 * mm)]

    story.append(Paragraph("Score distribution", styles["h2"]))
    story.append(_table(
        ["Band", "Applicants"],
        [[b.get("label"), sum(1 for r in data.rows if float(b.get("min", 0)) <= r.applicant.total_score <= float(b.get("max", 100)))] for b in data.score_bands],
        [60 * mm, 40 * mm],
        styles,
    ))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Role-wise summary", styles["h2"]))
    rows = []
    for role in data.roles:
        subset = role_shortlist(data.rows, role["id"])
        scores = [r.applicant.total_score for r in subset]
        rows.append([
            role.get("name"),
            len(subset),
            round(sum(scores) / len(scores), 2) if scores else 0,
            sum(1 for r in subset if r.applicant.eligibility_status == "PASS"),
            sum(1 for r in subset if r.applicant.review_status == "APPROVED"),
        ])
    story.append(_table(["Role", "Applicants", "Avg score", "Eligible", "Shortlisted"], rows, [65 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm], styles))
    return story


def _applicant_detail(row: ReportRow, styles: dict[str, ParagraphStyle], org: dict[str, Any], rubric_version: str) -> list[Any]:
    a = row.applicant
    e = row.evaluation
    story: list[Any] = []
    story.append(Paragraph(_esc(a.full_name or a.applicant_id), styles["h1"]))
    meta = (
        f"Applicant ID: {a.applicant_id} | Roles: {', '.join(a.roles) or '—'} | "
        f"Submitted: {a.submitted_at.strftime('%Y-%m-%d')} | Score: {a.total_score:.2f}/100 | "
        f"Recommendation: {a.recommendation} | Eligibility: {a.eligibility_status} | Rubric v{rubric_version}"
    )
    story.append(Paragraph(_esc(meta), styles["small"]))
    story.append(Spacer(1, 3 * mm))

    profile_rows = [
        ["Email", a.email, "USN", a.usn],
        ["Department", a.department, "Year", a.year_of_study],
        ["Processing status", a.processing_status, "Review status", a.review_status],
        ["Decision", a.review_decision or "Pending", "Reviewer", a.reviewed_by or "—"],
    ]
    story.append(_table(["Field", "Value", "Field", "Value"], profile_rows, [30 * mm, 55 * mm, 30 * mm, 55 * mm], styles))
    story.append(Spacer(1, 3 * mm))

    if e:
        story.append(Paragraph("AI summary", styles["h2"]))
        story.append(Paragraph(_esc(e.summary or "No summary available."), styles["body"]))
        story.append(Spacer(1, 2 * mm))

        story.append(Paragraph("Criterion-wise evaluation", styles["h2"]))
        crit_rows = [
            [c.name, f"{c.final_score:.2f}/{c.max_score:.0f}", "; ".join(c.evidence)[:500] or "No evidence recorded", c.reasoning[:300]]
            for c in e.criteria
        ]
        story.append(_table(["Criterion", "Score", "Evidence", "Reasoning"], crit_rows, [38 * mm, 20 * mm, 70 * mm, 44 * mm], styles))
        story.append(Spacer(1, 2 * mm))

        if e.eligibility:
            story.append(Paragraph("Eligibility checks", styles["h2"]))
            story.append(_table(
                ["Rule", "Status", "Detail"],
                [[r.label, r.status, r.detail] for r in e.eligibility],
                [55 * mm, 20 * mm, 97 * mm],
                styles,
            ))
            story.append(Spacer(1, 2 * mm))

        for title, values in (
            ("Strengths", e.strengths),
            ("Weaknesses", e.weaknesses),
            ("Missing information", e.missing_information),
            ("Inconsistencies / uncertain findings", e.inconsistencies + e.uncertain_findings),
        ):
            if values:
                story.append(Paragraph(title, styles["h2"]))
                for value in values:
                    story.append(Paragraph(f"• {_esc(value)}", styles["body"]))

        if e.interview_questions:
            story.append(Paragraph("Recommended interview questions", styles["h2"]))
            for index, q in enumerate(e.interview_questions, start=1):
                story.append(Paragraph(f"{index}. [{_esc(q.get('role'))}] {_esc(q.get('question'))}", styles["body"]))
                if q.get("why"):
                    story.append(Paragraph(f"<i>Why: {_esc(q.get('why'))}</i>", styles["small"]))

        if e.validation_errors:
            story.append(Paragraph("Validation warnings", styles["h2"]))
            for warning in e.validation_errors:
                story.append(Paragraph(f"• {_esc(warning)}", styles["small"]))

        if e.model_metadata:
            story.append(Paragraph("Model metadata", styles["h2"]))
            story.append(Paragraph(_esc(", ".join(f"{k}: {v}" for k, v in e.model_metadata.items())), styles["small"]))

    if a.review_notes:
        story.append(Paragraph("Human reviewer notes", styles["h2"]))
        story.append(Paragraph(_esc(a.review_notes), styles["body"]))

    story.append(Spacer(1, 4 * mm))
    return story


def build_pdf(
    data: ReportData,
    *,
    kind: str = "consolidated",
    applicant_id: str = "",
    role: str = "",
) -> bytes:
    styles = _styles()
    org = data.organization or {}
    rubric_version = data.rubric_version or "1.0.0"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="AWS Student Builder Group Recruitment Report",
        author=org.get("name", "AWS Student Builder Group"),
    )

    titles = {
        "consolidated": "Recruitment Evaluation Report",
        "executive": "Executive Summary",
        "role": f"Role Shortlist — {role}",
        "manual_review": "Manual Review Report",
        "applicant": "Applicant Evaluation Report",
    }
    story = _cover(data, styles, titles.get(kind, "Recruitment Report"), kind.replace("_", " ").title())
    story.append(PageBreak())

    if kind in ("executive", "consolidated", "manual_review", "role"):
        story += _summary_section(data, styles)

    if kind == "role":
        rows = role_shortlist(data.rows, role)
        story.append(PageBreak())
        story.append(Paragraph(f"Shortlist — {_esc(role)}", styles["h1"]))
        story.append(_table(
            ["Rank", "Applicant", "ID", "Score", "Recommendation", "Eligibility"],
            [[i + 1, r.applicant.full_name, r.applicant.applicant_id, f"{r.applicant.total_score:.2f}", r.applicant.recommendation, r.applicant.eligibility_status] for i, r in enumerate(rows)],
            [14 * mm, 45 * mm, 32 * mm, 18 * mm, 40 * mm, 25 * mm],
            styles,
        ))

    if kind == "manual_review":
        rows = manual_review_rows(data.rows)
        story.append(PageBreak())
        story.append(Paragraph("Manual review queue", styles["h1"]))
        story.append(_table(
            ["Applicant", "Score", "Recommendation", "Eligibility", "Reasons"],
            [[r.applicant.full_name, f"{r.applicant.total_score:.2f}", r.applicant.recommendation, r.applicant.eligibility_status, "; ".join(r.applicant.eligibility_failures)[:600]] for r in rows],
            [40 * mm, 18 * mm, 35 * mm, 22 * mm, 57 * mm],
            styles,
        ))

    if kind == "applicant":
        row = data.applicant(applicant_id) if applicant_id else (data.rows[0] if data.rows else None)
        if row:
            story += _applicant_detail(row, styles, org, rubric_version)

    if kind == "consolidated":
        story.append(PageBreak())
        story.append(Paragraph("Applicant evaluations", styles["h1"]))
        for index, row in enumerate(data.rows):
            story += _applicant_detail(row, styles, org, rubric_version)
            story.append(PageBreak() if index < len(data.rows) - 1 else Spacer(1, 1))

        shortlist = shortlisted_rows(data.rows)
        if shortlist:
            story.append(PageBreak())
            story.append(Paragraph("Approved interview shortlist", styles["h1"]))
            story.append(_table(
                ["Applicant", "Roles", "Score", "Approved by", "Notes"],
                [[r.applicant.full_name, ", ".join(r.applicant.roles), f"{r.applicant.total_score:.2f}", r.applicant.reviewed_by, r.applicant.review_notes[:200]] for r in shortlist],
                [38 * mm, 38 * mm, 18 * mm, 35 * mm, 43 * mm],
                styles,
            ))

    if kind == "executive":
        story.append(PageBreak())
        story.append(Paragraph("Interview shortlist", styles["h1"]))
        shortlist = shortlisted_rows(data.rows)
        if shortlist:
            story.append(_table(
                ["Applicant", "Roles", "Score", "Decision"],
                [[r.applicant.full_name, ", ".join(r.applicant.roles), f"{r.applicant.total_score:.2f}", r.applicant.review_decision] for r in shortlist],
                [50 * mm, 50 * mm, 20 * mm, 50 * mm],
                styles,
            ))
        else:
            story.append(Paragraph("No applicants have been approved for interview yet.", styles["body"]))

    doc.build(story, onFirstPage=_footer(org, org.get("cycle", "2026-27"), rubric_version), onLaterPages=_footer(org, org.get("cycle", "2026-27"), rubric_version))
    return buffer.getvalue()


def build_applicant_pdf(applicant: Applicant, evaluation: Optional[Evaluation], organization: dict[str, Any], rubric_version: str) -> bytes:
    data = ReportData(
        rows=[ReportRow(applicant, evaluation)],
        organization=organization,
        rubric_version=rubric_version,
        generated_at=datetime.utcnow(),
    )
    return build_pdf(data, kind="applicant", applicant_id=applicant.applicant_id)
