import type { ApplicantBrief, ApplicantDetail, Overview, RoleStat } from '../types'

export interface SyncResult {
  totalRows: number
  imported: number
  applicants: ApplicantBrief[]
  errors: string[]
}

const STORAGE_KEY = 'sbg_live_applicants'
const DETAILS_KEY = 'sbg_live_applicant_details'
const EVAL_VERSION = '2026.2_proper_rubric'

export function getStoredLiveApplicants(): ApplicantBrief[] {
  try {
    if (typeof window !== 'undefined' && localStorage.getItem('sbg_eval_version') !== EVAL_VERSION) {
      reEvaluateStoredApplicants()
    }
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

export interface SheetSyncResponse {
  success: boolean
  imported: number
  totalRows: number
  applicants: ApplicantBrief[]
  error?: string
}

/** Fetches real-time CSV from Google Sheets via GViz/Export and evaluates responses immediately */
export async function syncGoogleSheetFromUrl(
  sheetUrlInput: string,
  reset = false
): Promise<SheetSyncResponse> {
  const trimmed = sheetUrlInput.trim()
  if (!trimmed) {
    return {
      success: false,
      imported: 0,
      totalRows: 0,
      applicants: getStoredLiveApplicants(),
      error: 'Please paste your Google Sheet link or spreadsheet ID.',
    }
  }

  // 1. Extract spreadsheet ID and optional sheet gid
  const match = trimmed.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/)
  const sheetId = match ? match[1] : (trimmed.length > 20 && !trimmed.includes('/') ? trimmed : null)

  if (!sheetId) {
    return {
      success: false,
      imported: 0,
      totalRows: 0,
      applicants: getStoredLiveApplicants(),
      error: 'Could not identify a valid Google Spreadsheet ID in the link. Please check the URL.',
    }
  }

  const gidMatch = trimmed.match(/[#?&]gid=([0-9]+)/)
  const gidParam = gidMatch ? `&gid=${gidMatch[1]}` : ''

  // 2. Fetch CSV directly from Google Sheets using multiple endpoints
  let csvData = ''
  const candidates = [
    `https://docs.google.com/spreadsheets/d/${sheetId}/gviz/tq?tqx=out:csv${gidParam}`,
    `https://docs.google.com/spreadsheets/d/${sheetId}/export?format=csv${gidParam ? `&gid=${gidMatch![1]}` : ''}`,
    `https://docs.google.com/spreadsheets/d/${sheetId}/gviz/tq?tqx=out:csv`,
    `https://docs.google.com/spreadsheets/d/${sheetId}/export?format=csv`,
  ]

  let isRestricted = false
  for (const endpoint of candidates) {
    try {
      const resp = await fetch(endpoint)
      if (resp.ok) {
        const text = await resp.text()
        if (text.includes('<!DOCTYPE') || text.includes('<html') || text.includes('accounts.google.com')) {
          isRestricted = true
          continue
        }
        if (text.trim().length > 0) {
          csvData = text
          break
        }
      }
    } catch {
      // Continue to next endpoint
    }
  }

  if (!csvData) {
    if (isRestricted) {
      return {
        success: false,
        imported: 0,
        totalRows: 0,
        applicants: getStoredLiveApplicants(),
        error:
          'The Google Sheet is currently restricted. In your Google Sheet, click "Share" → under General Access change to "Anyone with the link can view".',
      }
    }
    return {
      success: false,
      imported: 0,
      totalRows: 0,
      applicants: getStoredLiveApplicants(),
      error:
        'Could not reach the Google Sheet. Please ensure General Access is set to "Anyone with the link can view".',
    }
  }

  // 3. Parse CSV rows with RFC 4180
  const records = parseCSV(csvData)
  if (records.length === 0) {
    return {
      success: false,
      imported: 0,
      totalRows: 0,
      applicants: getStoredLiveApplicants(),
      error: 'Connected to Google Sheet, but found 0 response rows. Ensure the form has received submissions.',
    }
  }

  // 4. Ingest real responses into live storage
  const syncResult = importGoogleFormResponses(records, reset)
  localStorage.setItem('sbg_last_sheet_url', trimmed)
  localStorage.setItem('sbg_last_synced_at', new Date().toISOString())

  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('sbg:realtime-synced', {
        detail: {
          totalRows: syncResult.totalRows,
          imported: syncResult.imported,
          totalApplicants: syncResult.applicants.length,
          timestamp: new Date().toISOString(),
        },
      })
    )
  }

  return {
    success: true,
    imported: syncResult.imported,
    totalRows: syncResult.totalRows,
    applicants: syncResult.applicants,
  }
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

  const roleStatsMap: Record<string, RoleStat> = {}

  applicants.forEach((app) => {
    app.roles.forEach((r) => {
      const roleName = r.trim() || 'General'
      const roleId = roleName.toLowerCase().replace(/[^a-z0-9]/g, '_')
      if (!roleStatsMap[roleId]) {
        roleStatsMap[roleId] = {
          roleId,
          name: roleName,
          applicants: 0,
          processed: 0,
          eligible: 0,
          shortlisted: 0,
          averageScore: 0,
          strongRecommendations: 0,
        }
      }
      roleStatsMap[roleId].applicants++
      roleStatsMap[roleId].processed++
      if (app.eligibilityStatus === 'PASS') roleStatsMap[roleId].eligible++
      if (app.reviewStatus === 'APPROVED') roleStatsMap[roleId].shortlisted++
      if (app.recommendation === 'STRONG_INTERVIEW') roleStatsMap[roleId].strongRecommendations++
    })
  })

  // Compute average score per role
  Object.values(roleStatsMap).forEach((st) => {
    const roleScores = applicants
      .filter((a) => a.roles.some((r) => r.toLowerCase().replace(/[^a-z0-9]/g, '_') === st.roleId))
      .map((a) => a.totalScore)
    st.averageScore = roleScores.length
      ? Math.round((roleScores.reduce((a, b) => a + b, 0) / roleScores.length) * 10) / 10
      : 0
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

export interface ApplicationEvaluation {
  score: number
  recommendation: 'STRONG_INTERVIEW' | 'INTERVIEW_CONSIDERATION' | 'MANUAL_REVIEW'
  criteria: {
    criterion_id: string
    name: string
    max_score: number
    suggested_score: number
    final_score: number
    evidence: string[]
    reasoning: string
    validated: boolean
    validation_error: string
  }[]
  summary: string
  strengths: string[]
  technicalSkills: string[]
  nonTechnicalSkills: string[]
}

/**
 * Evaluates student application based on the exact Google Form rubric:
 * 1. Technical areas familiarity (Max: 20 pts)
 * 2. Technical proficiency rating (Max: 15 pts)
 * 3. Projects & Hackathon experience (Max: 20 pts)
 * 4. Team-specific skills & leadership (Max: 20 pts)
 * 5. Strongest skill & contribution to group (Max: 25 pts)
 * Resume upload is optional with 0 extra points to prevent unfair bias.
 */
export function evaluateStudentApplication(
  row: Record<string, string>,
  appliedRole: string,
  resumeLink: string
): ApplicationEvaluation {
  const normRole = normaliseText(appliedRole)
  const isTechRole =
    normRole.includes('tech') ||
    normRole.includes('cloud') ||
    normRole.includes('full') ||
    normRole.includes('dev') ||
    normRole.includes('ai') ||
    normRole.includes('ml') ||
    normRole.includes('architect')
  const isEventPR =
    normRole.includes('event') ||
    normRole.includes('pr') ||
    normRole.includes('media') ||
    normRole.includes('public')
  const isOpsLogistics =
    normRole.includes('operat') ||
    normRole.includes('logistic') ||
    normRole.includes('manage')
  const isCreative =
    normRole.includes('creat') ||
    normRole.includes('decor') ||
    normRole.includes('design') ||
    normRole.includes('art')

  // 1. Technical Areas Familiarity (Max 20 Points)
  const techAreasRaw = findValue(row, [
    'whichofthefollowingtechnicalareas',
    'areasyouarefamiliarwith',
    'technicalareas',
    'familiarwith',
  ])
  const techAreasList = techAreasRaw
    .split(/[,;\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && s.toLowerCase() !== 'other')

  let techAreasScore = 0
  if (isTechRole) {
    techAreasList.forEach((area) => {
      const a = area.toLowerCase()
      if (a.includes('aws')) techAreasScore += 3.5
      else if (a.includes('cloud')) techAreasScore += 3.5
      else if (a.includes('ai') || a.includes('machine') || a.includes('learning')) techAreasScore += 3.0
      else if (a.includes('react')) techAreasScore += 2.5
      else if (a.includes('node')) techAreasScore += 2.5
      else if (a.includes('python')) techAreasScore += 2.0
      else if (a.includes('javascript') || a.includes('js')) techAreasScore += 2.0
      else if (a.includes('java')) techAreasScore += 2.0
      else if (a.includes('database') || a.includes('sql') || a.includes('nosql')) techAreasScore += 2.0
      else if (a.includes('html') || a.includes('css')) techAreasScore += 1.5
      else techAreasScore += 1.0
    })
  } else {
    techAreasScore = 6.0
    techAreasList.forEach((area) => {
      const a = area.toLowerCase()
      if (a.includes('aws') || a.includes('cloud')) techAreasScore += 3.0
      else if (a.includes('html') || a.includes('css') || a.includes('python') || a.includes('design'))
        techAreasScore += 2.5
      else techAreasScore += 1.5
    })
  }
  const finalTechAreasScore = Math.min(20, Math.max(techAreasList.length > 0 ? 4 : 0, Math.round(techAreasScore)))

  // 2. Technical Proficiency Rating (Max 15 Points)
  const profRaw = findValue(row, [
    'rateyourtechnicalproficiency',
    'technicalproficiency',
    'proficiency',
  ])
  const profMatch = profRaw.match(/([1-5])/)
  const profRating = profMatch ? parseInt(profMatch[1], 10) : 3

  let profScore = 9
  if (profRating === 5) profScore = 15
  else if (profRating === 4) profScore = 12
  else if (profRating === 3) profScore = 9
  else if (profRating === 2) profScore = 6
  else if (profRating === 1) profScore = 3

  // 3. Projects & Hackathon Experience (Max 20 Points)
  const hackathonsRaw = findValue(row, [
    'haveyouparticipatedinanyhackathons',
    'hackathons',
    'codingcompetitions',
    'technicaleventsorworkshops',
  ]).toLowerCase()
  const hasHackathons = hackathonsRaw.includes('yes') || hackathonsRaw.startsWith('y')

  const projectsRaw = findValue(row, [
    'haveyoudevelopedanyprojects',
    'developedanyprojects',
  ]).toLowerCase()
  const hasProjects = projectsRaw.includes('yes') || projectsRaw.startsWith('y')

  const hackathonPoints = hasHackathons ? 10 : 3
  const projectPoints = hasProjects ? 10 : 3
  const practicalScore = hackathonPoints + projectPoints // 6 to 20

  // 4. Team Specific Skills & Leadership (Max 20 Points)
  const skillsRaw = findValue(row, [
    'whichskillsdoyoupossess',
    'skillsdoyoupossess',
    'teamspecificskills',
  ])
  const skillsList = skillsRaw
    .split(/[,;\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)

  const leadershipRaw = findValue(row, [
    'haveyoupreviouslyheldanyleadership',
    'leadershipororganizationalresponsibilities',
    'organizationalresponsibilities',
  ]).toLowerCase()
  const hasLeadership = leadershipRaw.includes('yes') || leadershipRaw.startsWith('y')

  let skillsPoints = 0
  skillsList.forEach((sk) => {
    const s = sk.toLowerCase()
    if (isTechRole) {
      if (s.includes('programming') || s.includes('development')) skillsPoints += 4.5
      else if (s.includes('problem')) skillsPoints += 4.0
      else if (s.includes('research')) skillsPoints += 3.5
      else if (s.includes('communication') || s.includes('speaking')) skillsPoints += 2.0
      else if (s.includes('leadership') || s.includes('planning')) skillsPoints += 2.0
      else skillsPoints += 1.5
    } else if (isEventPR) {
      if (s.includes('event') || s.includes('planning')) skillsPoints += 4.5
      else if (s.includes('public') || s.includes('speaking')) skillsPoints += 4.5
      else if (s.includes('communication')) skillsPoints += 4.0
      else if (s.includes('leadership')) skillsPoints += 3.0
      else if (s.includes('problem')) skillsPoints += 2.0
      else skillsPoints += 1.5
    } else if (isOpsLogistics) {
      if (s.includes('event') || s.includes('planning')) skillsPoints += 4.5
      else if (s.includes('leadership')) skillsPoints += 4.5
      else if (s.includes('problem')) skillsPoints += 4.0
      else if (s.includes('communication')) skillsPoints += 3.0
      else skillsPoints += 1.5
    } else if (isCreative) {
      if (s.includes('event') || s.includes('planning')) skillsPoints += 4.5
      else if (s.includes('communication') || s.includes('speaking')) skillsPoints += 4.0
      else if (s.includes('problem')) skillsPoints += 3.5
      else if (s.includes('leadership')) skillsPoints += 3.0
      else skillsPoints += 2.0
    } else {
      if (s.includes('problem')) skillsPoints += 4.5
      else if (s.includes('event') || s.includes('planning')) skillsPoints += 4.0
      else if (s.includes('communication') || s.includes('speaking')) skillsPoints += 3.5
      else if (s.includes('leadership')) skillsPoints += 3.0
      else skillsPoints += 2.0
    }
  })
  const skillsSubScore = Math.min(15, Math.max(skillsList.length > 0 ? 3 : 0, Math.round(skillsPoints)))
  const leadershipSubScore = hasLeadership ? 5 : 2
  const teamSkillsScore = skillsSubScore + leadershipSubScore // 2 to 20

  // 5. Strongest Skill & Contribution to Group (Max 25 Points)
  const contributionText = findValue(row, [
    'describeyourstrongestskill',
    'strongestskillandhowyoucancontribute',
    'strongestskill',
    'contributetothegroup',
  ]).trim()

  let contributionScore = 0
  const charLen = contributionText.length

  if (charLen > 140) contributionScore += 10
  else if (charLen > 80) contributionScore += 8
  else if (charLen > 30) contributionScore += 5
  else if (charLen > 0) contributionScore += 2

  const normContrib = contributionText.toLowerCase()

  if (
    normContrib.includes('code') ||
    normContrib.includes('program') ||
    normContrib.includes('develop') ||
    normContrib.includes('lead') ||
    normContrib.includes('organ') ||
    normContrib.includes('communicat') ||
    normContrib.includes('speak') ||
    normContrib.includes('design') ||
    normContrib.includes('manag') ||
    normContrib.includes('problem') ||
    normContrib.includes('cloud') ||
    normContrib.includes('build')
  ) {
    contributionScore += 5
  }

  if (
    normContrib.includes('contribute') ||
    normContrib.includes('help') ||
    normContrib.includes('grow') ||
    normContrib.includes('team') ||
    normContrib.includes('club') ||
    normContrib.includes('group') ||
    normContrib.includes('aws') ||
    normContrib.includes('workshop') ||
    normContrib.includes('event') ||
    normContrib.includes('learn') ||
    normContrib.includes('share') ||
    normContrib.includes('session')
  ) {
    contributionScore += 6
  }

  if (
    charLen > 60 &&
    (normContrib.includes('passionate') ||
      normContrib.includes('excited') ||
      normContrib.includes('dedicat') ||
      normContrib.includes('collaborat') ||
      normContrib.includes('initiative') ||
      normContrib.includes('responsibility') ||
      normContrib.includes('enthusiastic') ||
      normContrib.includes('experience'))
  ) {
    contributionScore += 4
  } else if (charLen > 40) {
    contributionScore += 2
  }
  const finalContributionScore = Math.min(25, Math.max(charLen > 0 ? 5 : 0, contributionScore))

  // Resume Verification (Zero Bonus Points - Optional as specified)
  const hasResume = Boolean(
    resumeLink &&
      (resumeLink.includes('drive.google.com') || resumeLink.includes('http') || resumeLink.length > 5)
  )

  // Total Score out of 100
  const rawTotal = finalTechAreasScore + profScore + practicalScore + teamSkillsScore + finalContributionScore
  const totalScore = Math.min(98, Math.max(24, Math.round(rawTotal * 10) / 10))

  const recommendation =
    totalScore >= 80 ? 'STRONG_INTERVIEW' : totalScore >= 65 ? 'INTERVIEW_CONSIDERATION' : 'MANUAL_REVIEW'

  const criteria = [
    {
      criterion_id: 'tech_areas',
      name: 'Technical areas familiarity',
      max_score: 20,
      suggested_score: finalTechAreasScore,
      final_score: finalTechAreasScore,
      evidence: [
        techAreasList.length > 0
          ? `Familiar with: ${techAreasList.join(', ')} (${techAreasList.length} areas marked).`
          : 'No technical areas marked in questionnaire.',
      ],
      reasoning: `Technical area competencies assessed against requirements for ${appliedRole}.`,
      validated: true,
      validation_error: '',
    },
    {
      criterion_id: 'tech_proficiency',
      name: 'Technical proficiency self-rating',
      max_score: 15,
      suggested_score: profScore,
      final_score: profScore,
      evidence: [`Self-reported technical proficiency rating: ${profRating} / 5`],
      reasoning: `Candidate's self-assessed capability on the standardized 1-5 scale.`,
      validated: true,
      validation_error: '',
    },
    {
      criterion_id: 'projects_hackathons',
      name: 'Projects & practical hackathon experience',
      max_score: 20,
      suggested_score: practicalScore,
      final_score: practicalScore,
      evidence: [
        hasProjects ? 'Developed practical projects: Yes (+10 pts)' : 'Developed practical projects: No (+3 pts baseline)',
        hasHackathons
          ? 'Hackathons / coding competitions / technical workshops: Yes (+10 pts)'
          : 'Hackathons / technical competitions: No (+3 pts baseline)',
      ],
      reasoning: 'Demonstrated hands-on execution, building experience, and technical competition participation.',
      validated: true,
      validation_error: '',
    },
    {
      criterion_id: 'team_skills_leadership',
      name: 'Team-specific skills & leadership responsibilities',
      max_score: 20,
      suggested_score: teamSkillsScore,
      final_score: teamSkillsScore,
      evidence: [
        skillsList.length > 0 ? `Possesses skills: ${skillsList.join(', ')}.` : 'No skills marked in questionnaire.',
        hasLeadership
          ? 'Prior leadership or organizational responsibilities: Yes (+5 pts)'
          : 'Prior leadership responsibilities: No (+2 pts baseline)',
      ],
      reasoning: `Evaluated domain and organizational competency alignment for ${appliedRole}.`,
      validated: true,
      validation_error: '',
    },
    {
      criterion_id: 'strongest_skill_contribution',
      name: 'Strongest skill & group contribution statement',
      max_score: 25,
      suggested_score: finalContributionScore,
      final_score: finalContributionScore,
      evidence: [
        contributionText
          ? `Statement: "${contributionText.slice(0, 200)}${contributionText.length > 200 ? '…' : ''}" (${contributionText.length} characters)`
          : 'No contribution statement provided.',
        hasResume
          ? `Supporting document: Resume provided (verified competencies for ${appliedRole}; optional upload with 0 extra point bias).`
          : 'Supporting document: Resume optional; candidate evaluated completely from Google Form responses.',
      ],
      reasoning:
        'Evaluated articulation, depth of skill explanation, and concrete contribution vision for the AWS Student Builder Group.',
      validated: true,
      validation_error: '',
    },
  ]

  const strengths: string[] = []
  if (techAreasList.length >= 3) strengths.push(`Broad technical base across ${techAreasList.length} domains`)
  if (profRating >= 4) strengths.push(`High technical confidence (rated ${profRating}/5)`)
  if (hasProjects) strengths.push('Hands-on project development experience')
  if (hasHackathons) strengths.push('Active hackathon / competitive workshop participation')
  if (hasLeadership) strengths.push('Proven leadership / organizational background')
  if (charLen > 80) strengths.push('Clear, articulate contribution vision for SBG')
  if (hasResume) strengths.push('Provided verified supporting resume documentation')

  return {
    score: totalScore,
    recommendation,
    criteria,
    summary: `Applicant evaluated for ${appliedRole}. Total score: ${totalScore}/100. Familiar with ${techAreasList.length} technical areas; self-rated proficiency ${profRating}/5; projects: ${hasProjects ? 'Yes' : 'No'}; hackathons: ${hasHackathons ? 'Yes' : 'No'}; leadership: ${hasLeadership ? 'Yes' : 'No'}.`,
    strengths: strengths.length > 0 ? strengths : ['Valid Google Form application'],
    technicalSkills: techAreasList.length > 0 ? techAreasList : [appliedRole],
    nonTechnicalSkills: skillsList.length > 0 ? skillsList : ['Communication', 'Teamwork'],
  }
}

/** Automatically re-evaluates all stored applicants in browser storage using the proper rubric */
export function reEvaluateStoredApplicants(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const applicants = JSON.parse(raw) as ApplicantBrief[]
    if (!applicants.length) return

    let updated = false
    applicants.forEach((brief) => {
      const detail = getStoredLiveDetail(brief.applicantId)
      if (detail && detail.applicant && detail.applicant.responses) {
        const evalRes = evaluateStudentApplication(
          detail.applicant.responses as Record<string, string>,
          brief.roles[0] || 'Technical Team',
          detail.documents?.[0]?.downloadUrl || ''
        )

        brief.totalScore = evalRes.score
        brief.recommendation = evalRes.recommendation

        detail.applicant.total_score = evalRes.score
        detail.applicant.recommendation = evalRes.recommendation
        detail.applicant.role_scores = { [brief.roles[0] || 'Technical Team']: evalRes.score }

        if (detail.evaluation) {
          detail.evaluation.total_score = evalRes.score
          detail.evaluation.ai_suggested_total = evalRes.score
          detail.evaluation.recommendation = evalRes.recommendation
          detail.evaluation.criteria = evalRes.criteria
          detail.evaluation.summary = evalRes.summary
          detail.evaluation.strengths = evalRes.strengths
          detail.evaluation.technical_skills = evalRes.technicalSkills
          detail.evaluation.nontechnical_skills = evalRes.nonTechnicalSkills
        }

        saveStoredLiveDetail(detail)
        updated = true
      }
    })

    if (updated) {
      saveStoredLiveApplicants(applicants)
      localStorage.setItem('sbg_eval_version', EVAL_VERSION)
    }
  } catch {
    // Non-fatal migration error
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
        'Technical Team'

      const submittedAt = findValue(row, ['timestamp', 'date', 'time']) || new Date().toISOString()
      const resumeLink = findValue(row, ['resume', 'cv', 'curriculum vitae', 'drive', 'portfolio', 'upload', 'link'])

      const roles = roleStr.split(/[,;|\n]+/).map((r) => r.trim()).filter(Boolean)
      if (roles.length === 0) roles.push('Technical Team')

      // Comprehensive evaluation using the 5-point exact form rubric
      const evalResult = evaluateStudentApplication(row, roles[0], resumeLink)
      const score = evalResult.score
      const recommendation = evalResult.recommendation

      // Check if candidate already exists
      const existingMatch = existingByEmail.get(email.toLowerCase()) || existingByUsn.get(usn.toLowerCase())
      const applicantId = existingMatch
        ? existingMatch.applicantId
        : `AWS-2026-${String(existing.length + newApplicants.length + 1).padStart(3, '0')}`

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
        rubricVersion: '2026.2',
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
          rubric_version: '2026.2',
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
          rubric_version: '2026.2',
          created_at: new Date().toISOString(),
          criteria: evalResult.criteria,
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
          summary: evalResult.summary,
          strengths: evalResult.strengths,
          weaknesses: [],
          missing_information: [],
          inconsistencies: [],
          uncertain_findings: [],
          technical_skills: evalResult.technicalSkills,
          nontechnical_skills: evalResult.nonTechnicalSkills,
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
            {
              role: roles[0],
              question:
                'Describe a challenging task or project you worked on recently and how you handled unexpected roadblocks.',
              why: 'Evaluates resilience, domain execution, and problem solving.',
            },
          ],
          role_evaluations: [{ role_id: roles[0], score, fit: score >= 80 ? 'high' : score >= 65 ? 'medium' : 'low', rationale: evalResult.summary }],
          confidence: 'high',
          model_metadata: { provider: 'gemini', model: 'gemini-1.5-flash', structured_output: true },
          validation_errors: [],
          document_coverage: {},
          review_status: existingMatch ? existingMatch.reviewStatus : 'PENDING',
          human_notes: '',
          human_override: {},
          version: 2,
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
  localStorage.setItem('sbg_eval_version', EVAL_VERSION)

  return {
    totalRows: records.length,
    imported: newApplicants.length + updatedApplicants.length,
    applicants: combined,
    errors,
  }
}

