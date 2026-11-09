"""Excel report generation with openpyxl."""

from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Any, Iterable, Optional

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..common.models import iso
from .data import ReportData, ReportRow, manual_review_rows, role_shortlist, shortlisted_rows, summary_stats

NAVY = "0B1F3A"
AWS_ORANGE = "FF9900"
LIGHT = "F4F7FB"
WHITE = "FFFFFF"
RED = "FFD7D5"
GREEN = "D7F5E0"
AMBER = "FFF1CC"

THIN = Side(style="thin", color="D8DEE9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def safe_cell(value: Any) -> Any:
    """Prevent spreadsheet formula injection from untrusted application text."""
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value[:32000]
    if isinstance(value, (list, tuple)):
        return safe_cell(", ".join(map(str, value)))
    if isinstance(value, dict):
        return safe_cell(json.dumps(value, ensure_ascii=False, default=str)[:32000])
    return value


def _header(ws, title: str, subtitle: str = "") -> int:
    ws.merge_cells("A1:H1")
    cell = ws["A1"]
    cell.value = title
    cell.font = Font(name="Calibri", size=15, bold=True, color=WHITE)
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    ws.row_dimensions[1].height = 28
    if subtitle:
        ws.merge_cells("A2:H2")
        ws["A2"].value = subtitle
        ws["A2"].font = Font(size=9, italic=True, color="556070")
        ws["A2"].alignment = Alignment(indent=1)
        return 3
    return 2


def _write_table(
    ws,
    start_row: int,
    headers: list[str],
    rows: Iterable[list[Any]],
    widths: Optional[list[int]] = None,
    *,
    autofilter: bool = True,
    freeze: bool = True,
) -> int:
    for index, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=index, value=header)
        cell.font = Font(bold=True, color=WHITE, size=10)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        cell.border = BORDER
        if widths and index <= len(widths):
            ws.column_dimensions[get_column_letter(index)].width = widths[index - 1]
    ws.row_dimensions[start_row].height = 26

    row_number = start_row
    for row_number, row in enumerate(rows, start=start_row + 1):
        for column, value in enumerate(row, start=1):
            cell = ws.cell(row=row_number, column=column, value=safe_cell(value))
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if isinstance(value, (int, float)):
                cell.alignment = Alignment(vertical="top", horizontal="center")
        if (row_number - start_row) % 2 == 0:
            for column in range(1, len(headers) + 1):
                ws.cell(row=row_number, column=column).fill = PatternFill("solid", fgColor=LIGHT)

    last_row = max(row_number, start_row + 1)
    if autofilter:
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{last_row}"
    if freeze:
        ws.freeze_panes = f"A{start_row + 1}"
    return last_row


def _score_column(ws, column: int, first_row: int, last_row: int) -> None:
    if last_row < first_row:
        return
    ref = f"{get_column_letter(column)}{first_row}:{get_column_letter(column)}{last_row}"
    ws.conditional_formatting.add(
        ref,
        ColorScaleRule(start_type="num", start_value=0, start_color="F8696B", mid_type="num", mid_value=65, mid_color="FFEB84", end_type="num", end_value=100, end_color="63BE7B"),
    )


def _status_rules(ws, column: int, first_row: int, last_row: int) -> None:
    if last_row < first_row:
        return
    ref = f"{get_column_letter(column)}{first_row}:{get_column_letter(column)}{last_row}"
    ws.conditional_formatting.add(ref, CellIsRule(operator="equal", formula=['"FAIL"'], fill=PatternFill("solid", fgColor=RED)))
    ws.conditional_formatting.add(ref, CellIsRule(operator="equal", formula=['"PASS"'], fill=PatternFill("solid", fgColor=GREEN)))
    ws.conditional_formatting.add(ref, CellIsRule(operator="equal", formula=['"UNKNOWN"'], fill=PatternFill("solid", fgColor=AMBER)))


def _applicant_row(row: ReportRow) -> list[Any]:
    a = row.applicant
    return [
        a.applicant_id,
        a.full_name,
        a.email,
        a.usn,
        a.phone,
        a.department,
        a.year_of_study,
        ", ".join(a.roles),
        iso(a.submitted_at),
        a.processing_status,
        a.total_score,
        a.recommendation,
        a.eligibility_status,
        a.review_status,
        a.review_decision,
        a.review_notes,
        len(a.documents),
        ", ".join(d.filename for d in a.documents),
        len(a.eligibility_failures),
        a.urgent_review,
    ]


APPLICANT_HEADERS = [
    "Applicant ID", "Full Name", "Email", "USN", "Phone", "Department", "Year",
    "Roles", "Submitted At (UTC)", "Processing Status", "Total Score", "Recommendation",
    "Eligibility", "Review Status", "Decision", "Reviewer Notes", "Documents",
    "Document Names", "Eligibility Issues", "Urgent Review",
]
APPLICANT_WIDTHS = [22, 24, 30, 16, 14, 20, 8, 26, 22, 16, 10, 24, 12, 14, 16, 36, 10, 32, 12, 10]


def build_excel(data: ReportData, roles_config: dict[str, Any], rubric: dict[str, Any]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    stats = summary_stats(data.rows)
    org = data.organization or {}
    subtitle = (
        f"{org.get('name', 'AWS Student Builder Group')} | {org.get('institution', 'SJB Institute of Technology')} | "
        f"Cycle {org.get('cycle', '2026-27')} | Generated {data.generated_at.strftime('%Y-%m-%d %H:%M UTC')} | "
        f"Rubric v{data.rubric_version or rubric.get('version', '1.0.0')}"
    )

    # -- Summary ------------------------------------------------------------
    ws = wb.create_sheet("Summary")
    row = _header(ws, "Recruitment Report — Summary", subtitle)
    summary_pairs = [
        ("Total applications", stats["total"]),
        ("Processed", stats["processed"]),
        ("Pending processing", stats["pending"]),
        ("Failed processing", stats["failed"]),
        ("Eligible", stats["eligible"]),
        ("Ineligible (flagged for human verification)", stats["ineligible"]),
        ("Requiring manual review", stats["needs_review"]),
        ("Approved for interview", stats["shortlisted"]),
        ("Strong interview recommendations", stats["strong_interview"]),
        ("Average score", stats["average_score"]),
    ]
    r = row + 1
    for label, value in summary_pairs:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=LIGHT)
        ws.cell(row=r, column=2, value=value)
        ws.cell(row=r, column=1).border = BORDER
        ws.cell(row=r, column=2).border = BORDER
        r += 1
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 22

    r += 1
    ws.cell(row=r, column=1, value="Role-wise overview").font = Font(bold=True, size=12, color=NAVY)
    r += 1
    role_headers = ["Role", "Applicants", "Average Score", "Eligible", "Shortlisted"]
    for index, header in enumerate(role_headers, start=1):
        cell = ws.cell(row=r, column=index, value=header)
        cell.font = Font(bold=True, color=WHITE)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.border = BORDER
    r += 1
    for role in roles_config.get("roles", []):
        role_rows = role_shortlist(data.rows, role["id"])
        scores = [x.applicant.total_score for x in role_rows]
        values = [
            role.get("name"),
            len(role_rows),
            round(sum(scores) / len(scores), 2) if scores else 0,
            sum(1 for x in role_rows if x.applicant.eligibility_status == "PASS"),
            sum(1 for x in role_rows if x.applicant.review_status == "APPROVED"),
        ]
        for index, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=index, value=safe_cell(value))
            cell.border = BORDER
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="Score distribution").font = Font(bold=True, size=12, color=NAVY)
    r += 1
    for band in rubric.get("score_bands", []):
        low, high = float(band.get("min", 0)), float(band.get("max", 100))
        count = sum(1 for x in data.rows if low <= x.applicant.total_score <= high)
        ws.cell(row=r, column=1, value=f"{band.get('label')}").border = BORDER
        ws.cell(row=r, column=2, value=count).border = BORDER
        r += 1

    if data.truncated:
        ws.cell(row=r + 1, column=1, value="WARNING: report truncated at the applicant cap.").font = Font(color="C00000", bold=True)

    # -- All applicants -----------------------------------------------------
    ws = wb.create_sheet("All Applicants")
    row = _header(ws, "All Applicants", subtitle)
    last = _write_table(ws, row, APPLICANT_HEADERS, (_applicant_row(x) for x in data.rows), APPLICANT_WIDTHS)
    _score_column(ws, 11, row + 1, last)
    _status_rules(ws, 13, row + 1, last)

    # -- Eligibility --------------------------------------------------------
    ws = wb.create_sheet("Eligibility Results")
    row = _header(ws, "Eligibility Results", subtitle)
    headers = ["Applicant ID", "Full Name", "Overall Eligibility", "Rule", "Mandatory", "Status", "Detail", "Observed Value"]
    rows = []
    for item in data.rows:
        evaluation = item.evaluation
        if not evaluation or not evaluation.eligibility:
            rows.append([item.applicant.applicant_id, item.applicant.full_name, item.applicant.eligibility_status, "No evaluation", "", "UNKNOWN", "Evaluation not available", ""])
            continue
        for result in evaluation.eligibility:
            rows.append([
                item.applicant.applicant_id, item.applicant.full_name, evaluation.eligibility_status,
                result.label, "Yes" if result.mandatory else "No", result.status, result.detail, result.observed,
            ])
    last = _write_table(ws, row, headers, rows, [22, 24, 16, 40, 10, 12, 60, 30])
    _status_rules(ws, 6, row + 1, last)

    # -- Role sheets --------------------------------------------------------
    fixed_roles = {
        "technical_team": "Technical Team",
        "marketing_outreach": "Marketing & Outreach",
        "social_media": "Social Media",
        "creative_design": "Creative & Design",
        "operations_logistics": "Operations & Logistics",
    }
    used_titles = {"Summary", "All Applicants", "Eligibility Results", "Role-wise Rankings", "Manual Review", "Interview Shortlist", "Interview Evaluation", "Audit History"}
    for role in roles_config.get("roles", []):
        title = fixed_roles.get(role["id"], str(role.get("name", role["id"]))[:31])
        if title in used_titles:
            title = f"{title}"[:24] + " Roles"
        used_titles.add(title)
        ws = wb.create_sheet(title[:31])
        row = _header(ws, f"{role.get('name', role['id'])} — Applicants", subtitle)
        role_rows = role_shortlist(data.rows, role["id"])
        last = _write_table(ws, row, APPLICANT_HEADERS, (_applicant_row(x) for x in role_rows), APPLICANT_WIDTHS)
        _score_column(ws, 11, row + 1, last)

    # -- Role-wise rankings -------------------------------------------------
    ws = wb.create_sheet("Role-wise Rankings")
    row = _header(ws, "Role-wise Rankings", subtitle)
    headers = ["Role", "Rank", "Applicant ID", "Full Name", "Total Score", "Recommendation", "Eligibility", "Review Status"]
    rows = []
    for role in roles_config.get("roles", []):
        ranked = role_shortlist(data.rows, role["id"])
        for index, item in enumerate(ranked, start=1):
            rows.append([
                role.get("name"), index, item.applicant.applicant_id, item.applicant.full_name,
                item.applicant.total_score, item.applicant.recommendation, item.applicant.eligibility_status,
                item.applicant.review_status,
            ])
    last = _write_table(ws, row, headers, rows, [24, 8, 22, 26, 12, 24, 12, 14])
    _score_column(ws, 5, row + 1, last)

    # -- Manual review ------------------------------------------------------
    ws = wb.create_sheet("Manual Review")
    row = _header(ws, "Manual Review Queue", subtitle)
    review_rows = manual_review_rows(data.rows)
    headers = ["Applicant ID", "Full Name", "Roles", "Score", "Recommendation", "Eligibility", "Reasons", "Reviewer", "Notes"]
    rows = []
    for item in review_rows:
        reasons = list(item.applicant.eligibility_failures)
        if item.evaluation:
            reasons += item.evaluation.inconsistencies[:3]
            reasons += item.evaluation.validation_errors[:3]
            reasons += item.evaluation.uncertain_findings[:3]
        rows.append([
            item.applicant.applicant_id, item.applicant.full_name, ", ".join(item.applicant.roles),
            item.applicant.total_score, item.applicant.recommendation, item.applicant.eligibility_status,
            "; ".join(dict.fromkeys(reasons))[:2000], item.applicant.reviewed_by, item.applicant.review_notes,
        ])
    last = _write_table(ws, row, headers, rows, [22, 26, 26, 10, 24, 12, 70, 22, 40])
    _status_rules(ws, 6, row + 1, last)

    # -- Interview shortlist ------------------------------------------------
    ws = wb.create_sheet("Interview Shortlist")
    row = _header(ws, "Approved Interview Shortlist", subtitle)
    headers = ["Applicant ID", "Full Name", "Email", "USN", "Department", "Year", "Roles", "Score", "Recommendation", "Approved By", "Approved At", "Notes"]
    rows = []
    for item in shortlisted_rows(data.rows):
        a = item.applicant
        rows.append([
            a.applicant_id, a.full_name, a.email, a.usn, a.department, a.year_of_study, ", ".join(a.roles),
            a.total_score, a.recommendation, a.reviewed_by, iso(a.reviewed_at), a.review_notes,
        ])
    _write_table(ws, row, headers, rows, [22, 26, 30, 16, 20, 8, 26, 10, 24, 22, 22, 40])
    if not rows:
        ws.cell(row=row + 1, column=1, value="No applicants have been approved for interview yet.").font = Font(italic=True)

    # -- Interview evaluation template -------------------------------------
    ws = wb.create_sheet("Interview Evaluation")
    row = _header(ws, "Interview Evaluation Sheet", subtitle)
    headers = [
        "Applicant ID", "Full Name", "Role", "Interview Date", "Panel", "Technical (30)",
        "Communication (20)", "Problem Solving (20)", "Culture & Commitment (15)", "Leadership (15)",
        "Total (100)", "Recommendation", "Panel Notes",
    ]
    rows = [
        [item.applicant.applicant_id, item.applicant.full_name, ", ".join(item.applicant.roles), "", "", "", "", "", "", "", "", "", ""]
        for item in shortlisted_rows(data.rows)
    ]
    last = _write_table(ws, row, headers, rows, [22, 26, 26, 16, 20, 14, 16, 16, 20, 14, 12, 20, 40])
    for r in range(row + 1, last + 1):
        ws.cell(row=r, column=11, value=f"=SUM(F{r}:J{r})")
    dv = DataValidation(type="list", formula1='"Strong Hire,Hire,Hold,No Hire"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"L{row + 1}:L{max(last, row + 1)}")
    if not rows:
        ws.cell(row=row + 1, column=1, value="Shortlist applicants first to populate this sheet.").font = Font(italic=True)

    # -- Audit --------------------------------------------------------------
    ws = wb.create_sheet("Audit History")
    row = _header(ws, "Audit History", subtitle)
    headers = ["Timestamp (UTC)", "Audit ID", "Applicant ID", "Actor", "Action", "Reason", "Previous Value", "Updated Value"]
    rows = [
        [
            iso(entry.timestamp), entry.audit_id, entry.applicant_id, entry.reviewer, entry.action,
            entry.reason, json.dumps(entry.previous_value, ensure_ascii=False, default=str),
            json.dumps(entry.updated_value, ensure_ascii=False, default=str),
        ]
        for entry in data.audit
    ]
    _write_table(ws, row, headers, rows, [22, 30, 22, 22, 26, 30, 50, 60])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
