import jsPDF from 'jspdf'
import type { ApplicantBrief } from '../types'
import {
  canonicalizeRole,
  getApplicantContactPhone,
} from './googleSync'
import { formatDate } from './utils'

export interface ContactsPdfOptions {
  filename?: string
  roleFilter?: string
}

/**
 * Generates and downloads a clean, beautifully formatted vector PDF
 * containing the real applicant contact directory (Name, Mobile, Email, USN, Role).
 */
export function exportContactsPdf(
  applicants: ApplicantBrief[],
  options: ContactsPdfOptions = {}
): void {
  if (!applicants || applicants.length === 0) {
    throw new Error('No applicant contact data available to export.')
  }

  const doc = new jsPDF({
    orientation: 'landscape',
    unit: 'mm',
    format: 'a4',
  })

  const pageWidth = doc.internal.pageSize.getWidth() // 297mm
  const pageHeight = doc.internal.pageSize.getHeight() // 210mm
  const margin = 12
  const contentWidth = pageWidth - margin * 2 // 273mm

  // Table Columns Definition
  const cols = [
    { label: '#', width: 10, align: 'center' as const },
    { label: 'Candidate Name', width: 44, align: 'left' as const },
    { label: 'USN', width: 26, align: 'left' as const },
    { label: 'Mobile Number', width: 34, align: 'left' as const },
    { label: 'Email Address', width: 56, align: 'left' as const },
    { label: 'Department & Year', width: 44, align: 'left' as const },
    { label: 'Shortlisted / Applied Role', width: 59, align: 'left' as const },
  ]

  function drawHeader(isFirstPage: boolean) {
    if (isFirstPage) {
      // Top Navy Header Banner
      doc.setFillColor(15, 23, 42) // Navy 900
      doc.rect(0, 0, pageWidth, 28, 'F')

      // Orange AWS Accent Line
      doc.setFillColor(255, 153, 0) // AWS Orange
      doc.rect(0, 26.5, pageWidth, 1.5, 'F')

      // Organization Branding
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(13)
      doc.setTextColor(255, 255, 255)
      doc.text('AWS STUDENT BUILDER GROUP', margin, 10)

      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(203, 213, 225)
      doc.text(
        'SJB Institute of Technology, Bengaluru | Recruitment Cycle 2026–27',
        margin,
        15
      )

      doc.setFont('helvetica', 'bold')
      doc.setFontSize(8.5)
      doc.setTextColor(255, 153, 0)
      doc.text(
        'OFFICIAL APPLICANTS CONTACT & COMMUNICATION DIRECTORY',
        margin,
        21
      )

      // Right metadata
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7.5)
      doc.setTextColor(226, 232, 240)
      doc.text(
        `Generated: ${formatDate(new Date().toISOString())}`,
        pageWidth - margin,
        10,
        { align: 'right' }
      )
      doc.text(
        `Total Candidates: ${applicants.length}`,
        pageWidth - margin,
        15,
        { align: 'right' }
      )
      doc.text(
        'CLASSIFICATION: STRICTLY CONFIDENTIAL',
        pageWidth - margin,
        21,
        { align: 'right' }
      )

      return 34
    } else {
      // Compact top banner for subsequent pages
      doc.setFillColor(15, 23, 42)
      doc.rect(0, 0, pageWidth, 14, 'F')
      doc.setFillColor(255, 153, 0)
      doc.rect(0, 13, pageWidth, 1, 'F')

      doc.setFont('helvetica', 'bold')
      doc.setFontSize(9)
      doc.setTextColor(255, 255, 255)
      doc.text(
        'AWS STUDENT BUILDER GROUP (SJBIT) — APPLICANTS CONTACT DIRECTORY (2026–27)',
        margin,
        9
      )

      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7.5)
      doc.setTextColor(203, 213, 225)
      doc.text(
        `Total: ${applicants.length} Candidates`,
        pageWidth - margin,
        9,
        { align: 'right' }
      )

      return 18
    }
  }

  function drawTableHeader(y: number): number {
    const headerHeight = 7.5
    doc.setFillColor(241, 245, 249) // Slate 100
    doc.rect(margin, y, contentWidth, headerHeight, 'F')

    // Top border and bottom border
    doc.setDrawColor(203, 213, 225)
    doc.setLineWidth(0.3)
    doc.rect(margin, y, contentWidth, headerHeight)

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7.5)
    doc.setTextColor(30, 41, 59) // Slate 800

    let curX = margin
    for (const col of cols) {
      const textX =
        col.align === 'center'
          ? curX + col.width / 2
          : curX + 2
      doc.text(col.label, textX, y + 5, { align: col.align })
      curX += col.width
    }

    return y + headerHeight
  }

  let isFirstPage = true
  let currentY = drawHeader(isFirstPage)
  currentY = drawTableHeader(currentY)

  const rowHeight = 7.5
  const bottomLimit = pageHeight - 16

  applicants.forEach((app, idx) => {
    // Check if new page is needed
    if (currentY + rowHeight > bottomLimit) {
      doc.addPage('a4', 'landscape')
      isFirstPage = false
      currentY = drawHeader(false)
      currentY = drawTableHeader(currentY)
    }

    // Row Background (Alternating)
    if (idx % 2 === 1) {
      doc.setFillColor(248, 250, 252) // Light slate 50
      doc.rect(margin, currentY, contentWidth, rowHeight, 'F')
    }

    // Row bottom separator line
    doc.setDrawColor(226, 232, 240)
    doc.setLineWidth(0.15)
    doc.line(margin, currentY + rowHeight, margin + contentWidth, currentY + rowHeight)

    const phone = getApplicantContactPhone(app)
    const email = app.email || '—'
    const name = app.fullName || '—'
    const usn = app.usn || '—'
    const deptYear = `${app.department ? app.department.replace('Computer Science and Engineering', 'CSE').replace('Information Science', 'ISE') : '—'} (${app.yearOfStudy || '—'})`
    const role = app.shortlistPriority?.role || app.priority1?.role || (app.roles[0] ? canonicalizeRole(app.roles[0]) : '—')

    let curX = margin

    // 1. Sl No
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(100, 116, 139)
    doc.text(String(idx + 1), curX + cols[0].width / 2, currentY + 5, { align: 'center' })
    curX += cols[0].width

    // 2. Candidate Name
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    doc.setTextColor(15, 23, 42)
    const safeName = name.length > 25 ? `${name.substring(0, 23)}…` : name
    doc.text(safeName, curX + 2, currentY + 5)
    curX += cols[1].width

    // 3. USN
    doc.setFont('courier', 'bold')
    doc.setFontSize(7.5)
    doc.setTextColor(51, 65, 85)
    doc.text(usn, curX + 2, currentY + 5)
    curX += cols[2].width

    // 4. Mobile Number
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    doc.setTextColor(15, 23, 42) // Highlighted dark text
    doc.text(phone, curX + 2, currentY + 5)
    curX += cols[3].width

    // 5. Email Address
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(37, 99, 235) // Hyperlink blue
    const safeEmail = email.length > 34 ? `${email.substring(0, 32)}…` : email
    doc.text(safeEmail, curX + 2, currentY + 5)
    curX += cols[4].width

    // 6. Department & Year
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(71, 85, 105)
    const safeDept = deptYear.length > 28 ? `${deptYear.substring(0, 26)}…` : deptYear
    doc.text(safeDept, curX + 2, currentY + 5)
    curX += cols[5].width

    // 7. Shortlisted / Applied Role
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7.5)
    doc.setTextColor(15, 23, 42)
    const safeRole = role.length > 32 ? `${role.substring(0, 30)}…` : role
    doc.text(safeRole, curX + 2, currentY + 5)

    currentY += rowHeight
  })

  // Footers with page numbering on every page
  const totalPages = doc.getNumberOfPages()
  for (let i = 1; i <= totalPages; i++) {
    doc.setPage(i)

    // Footer divider line
    doc.setDrawColor(203, 213, 225)
    doc.setLineWidth(0.3)
    doc.line(margin, pageHeight - 10, margin + contentWidth, pageHeight - 10)

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(148, 163, 184)

    doc.text(
      'AWS Student Builder Group • SJB Institute of Technology Bengaluru • Recruitment Verification Dossier',
      margin,
      pageHeight - 6
    )

    doc.text(
      'CONFIDENTIAL • AUTHORIZED SBG LEADERSHIP ROSTER',
      pageWidth / 2,
      pageHeight - 6,
      { align: 'center' }
    )

    doc.text(
      `Page ${i} of ${totalPages}`,
      pageWidth - margin,
      pageHeight - 6,
      { align: 'right' }
    )
  }

  // Trigger browser download
  const safeFilter = options.roleFilter ? `_${options.roleFilter.replace(/[^a-zA-Z0-9]/g, '_')}` : ''
  const filename = options.filename || `SBG_SJBIT_Applicants_Contact_Directory_2026-27${safeFilter}.pdf`
  doc.save(filename)
}
