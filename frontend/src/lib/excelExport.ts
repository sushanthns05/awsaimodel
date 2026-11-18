import * as XLSX from 'xlsx'
import type { ApplicantBrief } from '../types'
import {
  COMMUNITY_ROLES,
  canonicalizeRole,
  getApplicantContactPhone,
  getStoredLiveDetail,
  roleMatchesFilter,
} from './googleSync'
import { formatDate } from './utils'

export interface ExcelExportOptions {
  filename?: string
  roleFilter?: string
}

/**
 * Generates and downloads a multi-sheet, executive-ready Excel workbook (.xlsx)
 * containing real applicant data, scores, rankings, and contact information.
 */
export function exportApplicantsToExcel(
  applicants: ApplicantBrief[],
  options: ExcelExportOptions = {}
): void {
  if (!applicants || applicants.length === 0) {
    throw new Error('No applicant records available to export.')
  }

  const wb = XLSX.utils.book_new()

  // 1. Build Sheet 1: Master Applicant Directory
  const masterRows = applicants.map((app, index) => {
    const detail = getStoredLiveDetail(app.applicantId)
    const phone = getApplicantContactPhone(app)
    const resumeLink = detail?.documents?.[0]?.downloadUrl || ''

    return {
      'Sl No': index + 1,
      'Applicant ID': app.applicantId,
      'Candidate Name': app.fullName || '—',
      'USN': app.usn || '—',
      'Mobile / Phone': phone,
      'Email Address': app.email || '—',
      'Department': app.department || '—',
      'Year of Study': app.yearOfStudy || '—',
      'Applied Roles': app.roles.map(canonicalizeRole).join(', ') || '—',
      'Priority 1 Role': app.priority1?.role || '—',
      'P1 Score': app.priority1?.score ?? '—',
      'P1 Rank': app.priority1 ? `#${app.priority1.rank}` : '—',
      'Priority 2 Role': app.priority2?.role || '—',
      'P2 Score': app.priority2?.score ?? '—',
      'P2 Rank': app.priority2 ? `#${app.priority2.rank}` : '—',
      'Shortlisted Role': app.shortlistPriority?.role || app.priority1?.role || app.roles[0] || '—',
      'Shortlist Source': app.shortlistPriority?.sourcePriority || 'Priority 1',
      'Shortlist Reason': app.shortlistPriority?.reason || 'Evaluated on role performance',
      'Total Score': app.totalScore,
      'Recommendation': app.recommendation.replace(/_/g, ' '),
      'Eligibility': app.eligibilityStatus === 'PASS' ? 'Eligible' : 'Needs Review',
      'Review Status': app.reviewStatus || 'PENDING',
      'Resume Available': resumeLink ? 'Yes' : 'No',
      'Resume Link': resumeLink || '—',
      'Submitted Date': formatDate(app.submittedAt),
    }
  })

  const wsMaster = XLSX.utils.json_to_sheet(masterRows)
  wsMaster['!cols'] = [
    { wch: 6 },  // Sl No
    { wch: 14 }, // Applicant ID
    { wch: 22 }, // Candidate Name
    { wch: 14 }, // USN
    { wch: 16 }, // Mobile
    { wch: 28 }, // Email
    { wch: 26 }, // Department
    { wch: 14 }, // Year
    { wch: 32 }, // Applied Roles
    { wch: 26 }, // P1 Role
    { wch: 10 }, // P1 Score
    { wch: 9 },  // P1 Rank
    { wch: 26 }, // P2 Role
    { wch: 10 }, // P2 Score
    { wch: 9 },  // P2 Rank
    { wch: 28 }, // Shortlisted Role
    { wch: 16 }, // Shortlist Source
    { wch: 40 }, // Shortlist Reason
    { wch: 12 }, // Total Score
    { wch: 24 }, // Recommendation
    { wch: 14 }, // Eligibility
    { wch: 14 }, // Review Status
    { wch: 16 }, // Resume Available
    { wch: 45 }, // Resume Link
    { wch: 22 }, // Submitted Date
  ]
  XLSX.utils.book_append_sheet(wb, wsMaster, 'All Applicants')

  // 2. Build Sheet 2: Contact Directory (Clean, focused contact roster for calling/WhatsApp/Email)
  const contactRows = applicants.map((app, index) => ({
    'Sl No': index + 1,
    'Candidate Name': app.fullName || '—',
    'USN': app.usn || '—',
    'Mobile / Phone Number': getApplicantContactPhone(app),
    'Email Address': app.email || '—',
    'Department': app.department || '—',
    'Year of Study': app.yearOfStudy || '—',
    'Shortlisted Role': app.shortlistPriority?.role || app.priority1?.role || app.roles[0] || '—',
    'Score': app.totalScore,
    'Recommendation': app.recommendation.replace(/_/g, ' '),
    'Review Status': app.reviewStatus || 'PENDING',
  }))

  const wsContact = XLSX.utils.json_to_sheet(contactRows)
  wsContact['!cols'] = [
    { wch: 6 },  // Sl No
    { wch: 24 }, // Name
    { wch: 14 }, // USN
    { wch: 18 }, // Mobile
    { wch: 30 }, // Email
    { wch: 28 }, // Department
    { wch: 14 }, // Year
    { wch: 28 }, // Shortlisted Role
    { wch: 10 }, // Score
    { wch: 24 }, // Recommendation
    { wch: 14 }, // Review Status
  ]
  XLSX.utils.book_append_sheet(wb, wsContact, 'Contact Directory')

  // 3. Build Sheet 3: Community Role Breakdown Summary
  const roleSummaryRows = COMMUNITY_ROLES.map((roleName) => {
    const inP1 = applicants.filter((a) => a.priority1 && roleMatchesFilter(a.priority1.role, roleName))
    const inP2 = applicants.filter((a) => a.priority2 && roleMatchesFilter(a.priority2.role, roleName))
    const allocated = applicants.filter((a) => a.shortlistPriority && roleMatchesFilter(a.shortlistPriority.role, roleName))
    const allInRole = applicants.filter((a) =>
      (a.priority1 && roleMatchesFilter(a.priority1.role, roleName)) ||
      (a.priority2 && roleMatchesFilter(a.priority2.role, roleName))
    )

    const scores = allInRole.map((a) => {
      if (a.priority1 && roleMatchesFilter(a.priority1.role, roleName)) return a.priority1.score
      if (a.priority2 && roleMatchesFilter(a.priority2.role, roleName)) return a.priority2.score
      return a.totalScore
    })

    const avgScore = scores.length ? Math.round((scores.reduce((sum, s) => sum + s, 0) / scores.length) * 10) / 10 : 0
    const maxScore = scores.length ? Math.max(...scores) : 0
    const topCandidate = allInRole.find((a) => (a.priority1?.score === maxScore || a.priority2?.score === maxScore || a.totalScore === maxScore))?.fullName || '—'

    return {
      'Community Role': roleName,
      'Total Candidates': allInRole.length,
      'Priority 1 Choices': inP1.length,
      'Priority 2 Choices': inP2.length,
      'Shortlisted Allocation': allocated.length,
      'Average Score': avgScore,
      'Highest Score': maxScore,
      'Top Candidate': topCandidate,
    }
  })

  const wsRoleSummary = XLSX.utils.json_to_sheet(roleSummaryRows)
  wsRoleSummary['!cols'] = [
    { wch: 34 }, // Community Role
    { wch: 18 }, // Total Candidates
    { wch: 18 }, // P1
    { wch: 18 }, // P2
    { wch: 22 }, // Shortlisted
    { wch: 14 }, // Avg Score
    { wch: 14 }, // Highest Score
    { wch: 24 }, // Top Candidate
  ]
  XLSX.utils.book_append_sheet(wb, wsRoleSummary, 'Role Statistics')

  // Generate binary Excel buffer and trigger browser download
  const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  const blob = new Blob([wbout], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })

  const safeFilter = options.roleFilter ? `_${options.roleFilter.replace(/[^a-zA-Z0-9]/g, '_')}` : ''
  const filename = options.filename || `SBG_SJBIT_Applicants_Recruitment_2026-27${safeFilter}.xlsx`

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
