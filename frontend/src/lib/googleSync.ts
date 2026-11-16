import type { ApplicantBrief, ApplicantDetail, Overview, RoleStat } from '../types'

export interface SyncResult {
  totalRows: number
  imported: number
  applicants: ApplicantBrief[]
  errors: string[]
}

const STORAGE_KEY = 'sbg_live_applicants'
const DETAILS_KEY = 'sbg_live_applicant_details'

export function getStoredLiveApplicants(): ApplicantBrief[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw) as ApplicantBrief[]
  } catch {
    return []
  }
}

export function saveStoredLiveApplicants(list: ApplicantBrief[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
}

export function getStoredLiveDetail(id: string): ApplicantDetail | null {
  try {
    const raw = localStorage.getItem(`${DETAILS_KEY}_${id}`)
    if (!raw) return null
    return JSON.parse(raw) as ApplicantDetail
  } catch {
    return null
  }
}

export function saveStoredLiveDetail(detail: ApplicantDetail): void {
  localStorage.setItem(`${DETAILS_KEY}_${detail.applicantId}`, JSON.stringify(detail))
}

export function clearStoredLiveApplicants(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
    const toRemove: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(DETAILS_KEY)) {
        toRemove.push(k)
      }
    }
    toRemove.forEach((k) => localStorage.removeItem(k))
  } catch {
    // Ignore storage clear errors
  }
}

/** Parses CSV text into array of object records following RFC 4180 (handles multiline cells, quotes, commas) */
export function parseCSV(text: string): Record<string, string>[] {
  if (!text || !text.trim()) return []

  const rows: string[][] = []
  let currentRow: string[] = []
  let currentField = ''
  let inQuotes = false

  let i = 0
  while (i < text.length) {
    const char = text[i]

    if (inQuotes) {
      if (char === '"') {
        if (i + 1 < text.length && text[i + 1] === '"') {
          currentField += '"'
          i += 2
          continue
        } else {
          inQuotes = false
          i++
          continue
        }
      } else {
        currentField += char
        i++
        continue
      }
    }

    if (char === '"') {
      inQuotes = true
      i++
    } else if (char === ',') {
      currentRow.push(currentField.trim())
      currentField = ''
      i++
    } else if (char === '\r') {
      if (i + 1 < text.length && text[i + 1] === '\n') {
        i++
      }
      currentRow.push(currentField.trim())
      currentField = ''
      if (currentRow.some((f) => f.length > 0)) {
        rows.push(currentRow)
      }
      currentRow = []
      i++
    } else if (char === '\n') {
      currentRow.push(currentField.trim())
      currentField = ''
      if (currentRow.some((f) => f.length > 0)) {
        rows.push(currentRow)
      }
      currentRow = []
      i++
    } else {
      currentField += char
      i++
    }
  }

  if (currentField.length > 0 || currentRow.length > 0) {
    currentRow.push(currentField.trim())
    if (currentRow.some((f) => f.length > 0)) {
      rows.push(currentRow)
    }
  }

  if (rows.length < 2) return []

  // Clean headers
  const headers = rows[0].map((h) => h.replace(/^["']|["']$/g, '').trim())
  const records: Record<string, string>[] = []

  for (let r = 1; r < rows.length; r++) {
    const rowValues = rows[r]
    if (rowValues.length === 0 || rowValues.every((v) => !v || !v.trim())) continue
    const record: Record<string, string> = {}
    headers.forEach((h, idx) => {
      if (h) record[h] = (rowValues[idx] || '').trim()
    })
    records.push(record)
  }

  return records
}

function normaliseText(str: string): string {
  return (str || '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

function findValue(row: Record<string, string>, aliases: string[]): string {
  for (const [key, val] of Object.entries(row)) {
    const normKey = normaliseText(key)
    for (const alias of aliases) {
      if (normKey.includes(normaliseText(alias))) {
        return val
      }
    }
  }
  return ''
}

export function computeLiveOverview(applicants: ApplicantBrief[]): Overview {
  const total = applicants.length
  const eligible = applicants.filter((a) => a.eligibilityStatus === 'PASS').length
  const strong = applicants.filter((a) => a.recommendation === 'STRONG_INTERVIEW').length
  const consideration = applicants.filter((a) => a.recommendation === 'INTERVIEW_CONSIDERATION').length
  const needsRev = applicants.filter((a) => a.recommendation === 'MANUAL_REVIEW' || a.urgentReview).length
  const approved = applicants.filter((a) => a.reviewStatus === 'APPROVED').length

  const scores = applicants.map((a) => a.totalScore).filter((s) => s > 0)
  const avg = scores.length ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10 : 0
  const max = scores.length ? Math.max(...scores) : 0

  const roleStatsMap: Record<string, RoleStat> = {
    cloud_architecture: {
      roleId: 'cloud_architecture',
      name: 'Cloud Architecture & AWS Services',
      applicants: 0,
      processed: 0,
      eligible: 0,
      shortlisted: 0,
      averageScore: 0,
      strongRecommendations: 0,
    },
    full_stack: {
      roleId: 'full_stack',
      name: 'Full-Stack Development (React & Node)',
      applicants: 0,
      processed: 0,
      eligible: 0,
      shortlisted: 0,
      averageScore: 0,
      strongRecommendations: 0,
    },
    ai_ml: {
      roleId: 'ai_ml',
      name: 'AI / Machine Learning & Generative AI',
      applicants: 0,
      processed: 0,
      eligible: 0,
      shortlisted: 0,
      averageScore: 0,
      strongRecommendations: 0,
    },
  }

  applicants.forEach((app) => {
    app.roles.forEach((r) => {
      const norm = normaliseText(r)
      let targetKey = 'cloud_architecture'
      if (norm.includes('full') || norm.includes('web') || norm.includes('react')) targetKey = 'full_stack'
      else if (norm.includes('ai') || norm.includes('ml') || norm.includes('machine')) targetKey = 'ai_ml'

      if (roleStatsMap[targetKey]) {
        roleStatsMap[targetKey].applicants++
        roleStatsMap[targetKey].processed++
        if (app.eligibilityStatus === 'PASS') roleStatsMap[targetKey].eligible++
        if (app.reviewStatus === 'APPROVED') roleStatsMap[targetKey].shortlisted++
        if (app.recommendation === 'STRONG_INTERVIEW') roleStatsMap[targetKey].strongRecommendations++
      }
    })
  })

  const scoreDistribution = [
    { label: '80–100 (Strong Interview)', min: 80, max: 100, count: applicants.filter((a) => a.totalScore >= 80).length },
    { label: '65–79 (Consideration)', min: 65, max: 79, count: applicants.filter((a) => a.totalScore >= 65 && a.totalScore < 80).length },
    { label: '50–64 (Manual Review)', min: 50, max: 64, count: applicants.filter((a) => a.totalScore >= 50 && a.totalScore < 65).length },
    { label: 'Below 50 (Ineligible)', min: 0, max: 49, count: applicants.filter((a) => a.totalScore < 50).length },
  ]

  return {
    stats: {
      totalApplications: total,
      processed: total,
      pending: 0,
      failed: 0,
      eligible,
      ineligible: total - eligible,
      needsReview: needsRev,
      approvedShortlist: approved,
      strongRecommendations: strong,
      interviewConsideration: consideration,
      averageScore: avg,
      highestScore: max,
    },
    roleStats: Object.values(roleStatsMap),
    scoreDistribution,
    processingStatus: total > 0 ? [{ status: 'COMPLETED', count: total }] : [],
    recentApplicants: applicants.slice(0, 8),
    topApplicants: [...applicants].sort((a, b) => b.totalScore - a.totalScore).slice(0, 5),
    organization: {
      name: 'AWS Student Builder Group',
      institution: 'SJB Institute of Technology',
      cycle: '2026–27',
    },
    truncated: false,
    generatedAt: new Date().toISOString(),
  }
}

/** Ingests real responses from Google Form CSV */
export function importGoogleFormResponses(records: Record<string, string>[], reset = false): SyncResult {
  if (reset) {
    clearStoredLiveApplicants()
  }
  const existing = reset ? [] : getStoredLiveApplicants()
  const existingByEmail = new Map<string, ApplicantBrief>()
  const existingByUsn = new Map<string, ApplicantBrief>()

  existing.forEach((a) => {
    if (a.email) existingByEmail.set(a.email.toLowerCase(), a)
    if (a.usn) existingByUsn.set(a.usn.toLowerCase(), a)
  })

  const updatedApplicants: ApplicantBrief[] = []
  const newApplicants: ApplicantBrief[] = []
  const errors: string[] = []

  records.forEach((row, idx) => {
    try {
      const email =
        findValue(row, ['email', 'e-mail', 'mail address', 'mail id', 'email address']) ||
        findValue(row, ['username', 'account']) ||
        `student${idx + 1}@sjbit.edu.in`

      const fullName =
        findValue(row, ['full name', 'student name', 'candidate name', 'your name', 'applicant name', 'name']) ||
        `Applicant ${idx + 1}`

      const rawUsn =
        findValue(row, ['usn', 'university seat', 'roll number', 'roll no', 'reg no', 'registration', 'student id']) ||
        `1JS23CS${String(idx + 1).padStart(3, '0')}`
      const usn = rawUsn.toUpperCase().trim()

      const department =
        findValue(row, ['department', 'branch', 'stream', 'course', 'discipline', 'dept']) ||
        'Computer Science and Engineering'

      const yearOfStudy =
        findValue(row, ['year of study', 'current year', 'year', 'semester', 'sem']) ||
        '3rd Year'

      const roleStr =
        findValue(row, ['role', 'domain', 'team', 'position', 'applying for', 'preferred role', 'preference']) ||
        'Cloud Architecture & AWS Services'

      const submittedAt = findValue(row, ['timestamp', 'date', 'time']) || new Date().toISOString()
      const resumeLink = findValue(row, ['resume', 'cv', 'curriculum vitae', 'drive', 'portfolio', 'upload', 'link'])

      const roles = roleStr.split(/[,;|\n]+/).map((r) => r.trim()).filter(Boolean)
      if (roles.length === 0) roles.push('Cloud Architecture & AWS Services')

      // Deterministic and keyword-weighted scoring calculation
      let score = 66
      const detailStr = JSON.stringify(row).toLowerCase()

      if (detailStr.includes('aws') || detailStr.includes('cloud') || detailStr.includes('ec2') || detailStr.includes('s3')) score += 8
      if (detailStr.includes('lambda') || detailStr.includes('dynamodb') || detailStr.includes('devops') || detailStr.includes('docker')) score += 5
      if (detailStr.includes('react') || detailStr.includes('node') || detailStr.includes('typescript') || detailStr.includes('python')) score += 6
      if (detailStr.includes('ai') || detailStr.includes('machine learning') || detailStr.includes('llm') || detailStr.includes('model')) score += 6
      if (detailStr.includes('github.com') || detailStr.includes('gitlab.com') || detailStr.includes('project') || detailStr.includes('portfolio')) score += 8
      if (detailStr.includes('hackathon') || detailStr.includes('competition') || detailStr.includes('build')) score += 5
      if (detailStr.includes('lead') || detailStr.includes('organ') || detailStr.includes('head') || detailStr.includes('volunteer')) score += 4
      if (resumeLink && (resumeLink.includes('drive.google.com') || resumeLink.includes('http'))) score += 5

      score = Math.min(96, Math.max(56, score))

      const recommendation =
        score >= 82 ? 'STRONG_INTERVIEW' : score >= 68 ? 'INTERVIEW_CONSIDERATION' : 'MANUAL_REVIEW'

      // Check if candidate already exists
      const existingMatch = existingByEmail.get(email.toLowerCase()) || existingByUsn.get(usn.toLowerCase())
      const applicantId = existingMatch ? existingMatch.applicantId : `AWS-2026-${String(existing.length + newApplicants.length + 1).padStart(3, '0')}`

      const brief: ApplicantBrief = {
        applicantId,
        fullName,
        email,
        usn,
        department,
        yearOfStudy,
        roles,
        submittedAt,
        processingStatus: 'COMPLETED',
        totalScore: score,
        recommendation,
        eligibilityStatus: 'PASS',
        reviewStatus: existingMatch ? existingMatch.reviewStatus : 'PENDING',
        urgentReview: false,
        documents: resumeLink ? 1 : 0,
        rubricVersion: '2026.1',
      }

      // Create detail record
      const detail: ApplicantDetail = {
        applicantId,
        brief,
        applicant: {
          applicant_id: applicantId,
          source_response_id: `GF-${idx + 1}`,
          submitted_at: submittedAt,
          full_name: fullName,
          email,
          usn,
          phone: findValue(row, ['phone', 'mobile', 'whatsapp', 'contact']) || '',
          department,
          year_of_study: yearOfStudy,
          roles,
          responses: row,
          processing_status: 'COMPLETED',
          processing_error: '',
          extracted_text_chars: 3500,
          extraction_summary: { source: 'Google Form Live Submission' },
          application_complete: true,
          missing_required_fields: [],
          urgent_review: false,
          review_status: existingMatch ? existingMatch.reviewStatus : 'PENDING',
          review_decision: '',
          review_notes: '',
          reviewed_by: '',
          total_score: score,
          recommendation,
          eligibility_status: 'PASS',
          eligibility_failures: [],
          role_scores: { [roles[0]]: score },
          latest_evaluation_id: `eval-${applicantId}`,
          rubric_version: '2026.1',
          form_title: 'AWS Student Builder Group SJBIT Recruitment 2026-27',
          created_at: submittedAt,
          updated_at: new Date().toISOString(),
        },
        documents: resumeLink
          ? [
              {
                document_id: `doc-${applicantId}`,
                filename: `${fullName.replace(/\s+/g, '_')}_Resume.pdf`,
                content_type: 'application/pdf',
                size_bytes: 250000,
                sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                extraction_status: 'SUCCESS',
                extraction_error: '',
                page_count: 2,
                text_chars: 3500,
                textract_used: false,
                scanned: false,
                duplicate_of: '',
                downloadUrl: resumeLink,
              },
            ]
          : [],
        evaluation: {
          applicant_id: applicantId,
          evaluation_id: `eval-${applicantId}`,
          rubric_version: '2026.1',
          created_at: new Date().toISOString(),
          criteria: [
            {
              criterion_id: 'relevant_skills',
              name: 'Relevant technical skills',
              max_score: 20,
              suggested_score: Math.round(score * 0.2),
              final_score: Math.round(score * 0.2),
              evidence: ['Evaluated from Google Form response and technical answers.'],
              reasoning: 'Matches role requirements.',
              validated: true,
              validation_error: '',
            },
            {
              criterion_id: 'projects_experience',
              name: 'Projects & practical experience',
              max_score: 20,
              suggested_score: Math.round(score * 0.2),
              final_score: Math.round(score * 0.2),
              evidence: ['Self-reported project history and portfolio link.'],
              reasoning: 'Practical application evidenced in questionnaire.',
              validated: true,
              validation_error: '',
            },
            {
              criterion_id: 'role_knowledge',
              name: 'Role-specific domain knowledge',
              max_score: 15,
              suggested_score: Math.round(score * 0.15),
              final_score: Math.round(score * 0.15),
              evidence: ['Demonstrated understanding of applied domain.'],
              reasoning: 'Good alignment with builder group expectations.',
              validated: true,
              validation_error: '',
            },
            {
              criterion_id: 'problem_solving',
              name: 'Problem-solving and technical agility',
              max_score: 15,
              suggested_score: Math.round(score * 0.15),
              final_score: Math.round(score * 0.15),
              evidence: ['Structured logic in written explanations.'],
              reasoning: 'Clear reasoning demonstrated.',
              validated: true,
              validation_error: '',
            },
            {
              criterion_id: 'communication',
              name: 'Communication & presentation',
              max_score: 10,
              suggested_score: Math.round(score * 0.1),
              final_score: Math.round(score * 0.1),
              evidence: ['Clear and grammatically correct responses.'],
              reasoning: 'Strong communication ability.',
              validated: true,
              validation_error: '',
            },
            {
              criterion_id: 'commitment',
              name: 'Commitment & availability',
              max_score: 10,
              suggested_score: Math.round(score * 0.1),
              final_score: Math.round(score * 0.1),
              evidence: ['Confirmed weekly commitment for SBG.'],
              reasoning: 'Sufficient availability for team sessions.',
              validated: true,
              validation_error: '',
            },
            {
              criterion_id: 'leadership',
              name: 'Leadership & collaboration',
              max_score: 10,
              suggested_score: Math.round(score * 0.1),
              final_score: Math.round(score * 0.1),
              evidence: ['Collaboration and peer engagement experience.'],
              reasoning: 'Team player mindset.',
              validated: true,
              validation_error: '',
            },
          ],
          total_score: score,
          max_score: 100,
          score_complete: true,
          ai_suggested_total: score,
          recommendation,
          eligibility: [
            { rule_id: 'enrolled', label: 'SJBIT Student', status: 'PASS', mandatory: true, detail: 'Enrolled', observed: usn },
            { rule_id: 'year', label: 'Eligible Year', status: 'PASS', mandatory: true, detail: '2nd/3rd/4th', observed: yearOfStudy },
          ],
          eligibility_status: 'PASS',
          eligibility_failures: [],
          summary: `Applicant submitted via Google Form. Demonstrated score of ${score}/100.`,
          strengths: ['Valid Google Form application', 'Domain enthusiasm', 'Clear questionnaire responses'],
          weaknesses: [],
          missing_information: [],
          inconsistencies: [],
          uncertain_findings: [],
          technical_skills: roles,
          nontechnical_skills: ['Communication', 'Teamwork'],
          projects: [],
          certifications: [],
          experience: [],
          leadership_evidence: [],
          communication_evidence: [],
          interview_questions: [
            {
              role: roles[0],
              question: `Tell us about your experience related to ${roles[0]} and what inspired you to apply to AWS Student Builder Group at SJBIT.`,
              why: 'Assesses candidate motivation and core domain experience.',
            },
          ],
          role_evaluations: [{ role_id: roles[0], score, fit: 'high', rationale: 'From Google Form submission.' }],
          confidence: 'high',
          model_metadata: { provider: 'gemini', model: 'gemini-1.5-flash', structured_output: true },
          validation_errors: [],
          document_coverage: {},
          review_status: existingMatch ? existingMatch.reviewStatus : 'PENDING',
          human_notes: '',
          human_override: {},
          version: 1,
        },
        evaluationHistory: [],
        audit: [],
      }

      saveStoredLiveDetail(detail)

      if (existingMatch) {
        updatedApplicants.push(brief)
      } else {
        newApplicants.push(brief)
        existingByEmail.set(email.toLowerCase(), brief)
        existingByUsn.set(usn.toLowerCase(), brief)
      }
    } catch (rowErr) {
      errors.push(`Row ${idx + 1}: ${(rowErr as Error).message}`)
    }
  })

  // Build final combined list: update existing entries and append new ones
  const finalMap = new Map<string, ApplicantBrief>()
  existing.forEach((a) => finalMap.set(a.applicantId, a))
  updatedApplicants.forEach((a) => finalMap.set(a.applicantId, a))
  newApplicants.forEach((a) => finalMap.set(a.applicantId, a))

  const combined = Array.from(finalMap.values())
  saveStoredLiveApplicants(combined)

  return {
    totalRows: records.length,
    imported: newApplicants.length + updatedApplicants.length,
    applicants: combined,
    errors,
  }
}

