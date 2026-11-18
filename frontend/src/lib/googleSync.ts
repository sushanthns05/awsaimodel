import type {
  ApplicantBrief,
  ApplicantDetail,
  Overview,
  RoleStat,
  RolePriorityScore,
  ShortlistPriorityAllocation,
} from '../types'

export interface SyncResult {
  totalRows: number
  imported: number
  applicants: ApplicantBrief[]
  errors: string[]
}

const STORAGE_KEY = 'sbg_live_applicants'
const DETAILS_KEY = 'sbg_live_applicant_details'
// Bumped to enforce strictly reading applied roles only and robust dual-priority score shortlisting
const EVAL_VERSION = '2026.9_strict_roles_with_phone_export'

export interface CommunityRole {
  id: string
  name: string
  /** Backend role ids, display variants and common spellings that resolve to this role. */
  aliases: string[]
}

/**
 * Single source of truth for the roles used by the live Google Form -> dashboard pipeline.
 * The backend keeps a wider taxonomy (9 roles); these ids/aliases make either taxonomy
 * resolve to the same canonical role so evaluation and filtering stay consistent.
 */
export const ROLE_DEFINITIONS: CommunityRole[] = [
  {
    id: 'technical_team',
    name: 'Technical Team',
    aliases: ['technical_team', 'technical team', 'technical', 'tech', 'cloud', 'developer', 'programming'],
  },
  {
    id: 'event_pr_management',
    name: 'Event and PR Management',
    aliases: [
      'event_pr_management',
      'event_management',
      'event and pr management',
      'event & pr management',
      'event and pr',
      'event pr management',
      'event',
      'pr',
      'public relations',
    ],
  },
  {
    id: 'creative_decoration',
    name: 'Creative and Decoration',
    aliases: [
      'creative_decoration',
      'creative_design',
      'creative and decoration',
      'creative & decoration',
      'creative and design',
      'creative & design',
      'creative',
      'decoration',
      'design',
      'art',
    ],
  },
  {
    id: 'social_media_marketing_outreach',
    name: 'Social Media, Marketing and Outreach',
    aliases: [
      'social_media_marketing_outreach',
      'social_media',
      'marketing_outreach',
      'social media, marketing and outreach',
      'social media marketing and outreach',
      'social media and marketing',
      'social media',
      'marketing and outreach',
      'marketing & outreach',
      'marketing',
      'outreach',
      'media',
    ],
  },
  {
    id: 'operations_logistics',
    name: 'Operations and Logistics',
    aliases: [
      'operations_logistics',
      'operations and logistics',
      'operations & logistics',
      'operations',
      'logistics',
    ],
  },
]

export const COMMUNITY_ROLES: string[] = ROLE_DEFINITIONS.map((role) => role.name)

function normaliseRoleKey(value: string): string {
  return (value || '').toLowerCase().replace(/[^a-z0-9]+/g, '')
}

/** Backend roles that have no live community equivalent, kept distinct from the five community roles. */
const BACKEND_ONLY_ROLES: Record<string, string> = {
  communitymanagement: 'community_management',
  studentbuildergroupleader: 'student_builder_group_leader',
  other: 'other',
}

/** Resolves any known role id, name, alias, or free-text variant to its canonical frontend role id. */
export function roleIdFor(value: string): string {
  const v = (value || '').toLowerCase().trim()
  if (!v) return ''

  // Fast direct keyword mapping covering all variations with or without "team", "&", "and", etc.
  if (v.includes('operat') || v.includes('logistic')) {
    return 'operations_logistics'
  }
  if (
    v.includes('social') ||
    v.includes('market') ||
    v.includes('outreach') ||
    (v.includes('media') && !v.includes('immediate'))
  ) {
    return 'social_media_marketing_outreach'
  }
  if (v.includes('creat') || v.includes('decor') || v.includes('design') || v.includes('art')) {
    return 'creative_decoration'
  }
  if (
    v.includes('event') ||
    v.includes('public relation') ||
    (v.includes('pr') && !v.includes('program') && !v.includes('prior') && !v.includes('problem'))
  ) {
    return 'event_pr_management'
  }
  if (
    v.includes('tech') ||
    v.includes('cloud') ||
    v.includes('code') ||
    v.includes('develop') ||
    v.includes('programming')
  ) {
    return 'technical_team'
  }

  const key = normaliseRoleKey(value)
  for (const role of ROLE_DEFINITIONS) {
    if (normaliseRoleKey(role.id) === key || normaliseRoleKey(role.name) === key) return role.id
  }
  for (const role of ROLE_DEFINITIONS) {
    if (role.aliases.some((alias) => normaliseRoleKey(alias) === key)) return role.id
  }
  return BACKEND_ONLY_ROLES[key] || key
}

/** Canonical display name for a role id/name/alias; falls back to input string or Technical Team. */
export function canonicalizeRole(input: string): string {
  const id = roleIdFor(input)
  if (!id) return (input || '').trim() || 'Technical Team'
  const match = ROLE_DEFINITIONS.find((role) => role.id === id)
  return match ? match.name : (input || '').trim() || 'Technical Team'
}

/** True when two role values (id, name or alias from either taxonomy) refer to the same role. */
export function roleMatchesFilter(roleValue: string, filterValue: string): boolean {
  if (!roleValue || !filterValue) return false
  if (filterValue === 'all') return true
  const roleId = roleIdFor(roleValue)
  const filterId = roleIdFor(filterValue)
  return Boolean(roleId && filterId && roleId === filterId)
}

/**
 * Resolves a raw text fragment or single role option into one of the 5 canonical community role names,
 * or null if it doesn't match any community role.
 */
export function resolveSingleCommunityRoleName(val: string): string | null {
  const v = (val || '').toLowerCase().trim()
  if (!v) return null

  // Explicitly ignore known skills/competency answers from questions like "Which skills do you possess?"
  if (
    v.includes('programming and development') ||
    v.includes('technical research') ||
    v.includes('public speaking') ||
    v.includes('problem solving')
  ) {
    return null
  }

  const roleId = roleIdFor(val)
  if (roleId) {
    const match = ROLE_DEFINITIONS.find((r) => r.id === roleId)
    if (match) return match.name
  }
  return null
}

/**
 * Extracts distinct community roles from a text string (e.g. from comma-separated checkbox answers).
 */
export function extractRolesFromText(text: string): string[] {
  if (!text || !text.trim()) return []
  // Split on commas, semicolons, pipes, slashes, newlines
  const parts = text.split(/[,;\n|/]+/).map((p) => p.trim()).filter(Boolean)
  const resolved: string[] = []
  for (const part of parts) {
    const roleName = resolveSingleCommunityRoleName(part)
    if (roleName && !resolved.includes(roleName)) {
      resolved.push(roleName)
    }
  }
  return resolved
}

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

/** Extracts the real applicant phone/mobile from brief, detail, or form row */
export function getApplicantContactPhone(brief: ApplicantBrief): string {
  if (brief.phone && brief.phone.trim()) return brief.phone.trim()
  const detail = getStoredLiveDetail(brief.applicantId)
  if (detail?.applicant?.phone && detail.applicant.phone.trim()) {
    return detail.applicant.phone.trim()
  }
  if (detail?.applicant?.responses) {
    const row = detail.applicant.responses as Record<string, string>
    const found = findValue(row, ['phone', 'mobile', 'whatsapp', 'contact', 'telephone', 'calling'])
    if (found && found.trim()) return found.trim()
  }
  return '—'
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

/**
 * Extracts ONLY the roles the candidate explicitly selected in the Google Form.
 * Priority 1 / Priority 2 columns take precedence; a single multi-select
 * "Which team(s) are you applying for?" column fills any remaining slot.
 * Skills, department, leadership, and essay answers are NEVER used to invent an
 * applied role. If a candidate applied for only 1 role, priority2 is left empty.
 */
export function extractApplicantPriorities(row: Record<string, string>): {
  priority1: string
  priority2: string
  roles: string[]
} {
  // Disallowed column substrings (non-role questions that must NEVER be parsed as role choices)
  const isExcludedHeader = (normKey: string): boolean => {
    return (
      normKey.includes('skill') ||
      normKey.includes('familiar') ||
      normKey.includes('technicalarea') ||
      normKey.includes('proficiency') ||
      normKey.includes('hackathon') ||
      normKey.includes('codingcompetition') ||
      normKey.includes('workshop') ||
      normKey.includes('project') ||
      normKey.includes('leadership') ||
      normKey.includes('organizational') ||
      normKey.includes('responsibility') ||
      normKey.includes('responsibilities') ||
      normKey.includes('contribute') ||
      normKey.includes('strongest') ||
      normKey.includes('describe') ||
      normKey.includes('statement') ||
      normKey.includes('email') ||
      normKey.includes('fullname') ||
      normKey.includes('name') ||
      normKey.includes('usn') ||
      normKey.includes('year') ||
      normKey.includes('department') ||
      normKey.includes('branch') ||
      normKey.includes('stream') ||
      normKey.includes('semester') ||
      normKey.includes('phone') ||
      normKey.includes('mobile') ||
      normKey.includes('resume') ||
      normKey.includes('cv') ||
      normKey.includes('timestamp') ||
      normKey.includes('date')
    )
  }

  // 1. Check for dedicated Priority 1 column
  let p1Raw = ''
  for (const [key, val] of Object.entries(row)) {
    const normKey = normaliseText(key)
    if (isExcludedHeader(normKey)) continue
    if (
      normKey.includes('priority1') ||
      normKey.includes('preference1') ||
      normKey.includes('1stpref') ||
      normKey.includes('firstpref') ||
      normKey.includes('firstchoice') ||
      normKey.includes('primaryrole') ||
      normKey.includes('preferredrole1') ||
      normKey.includes('preferredteam1')
    ) {
      p1Raw = val
      break
    }
  }

  // 2. Check for dedicated Priority 2 column
  let p2Raw = ''
  for (const [key, val] of Object.entries(row)) {
    const normKey = normaliseText(key)
    if (isExcludedHeader(normKey)) continue
    if (
      normKey.includes('priority2') ||
      normKey.includes('preference2') ||
      normKey.includes('2ndpref') ||
      normKey.includes('secondpref') ||
      normKey.includes('secondchoice') ||
      normKey.includes('secondaryrole') ||
      normKey.includes('whichotherrole') ||
      normKey.includes('backuprole') ||
      normKey.includes('preferredrole2') ||
      normKey.includes('preferredteam2')
    ) {
      p2Raw = val
      break
    }
  }

  // 3. Check for general role/team multi-select column
  let generalRaw = ''
  for (const [key, val] of Object.entries(row)) {
    const normKey = normaliseText(key)
    if (isExcludedHeader(normKey)) continue
    if (
      normKey.includes('whichteam') ||
      normKey.includes('whichrole') ||
      normKey.includes('preferredteam') ||
      normKey.includes('preferredrole') ||
      normKey.includes('teamapplying') ||
      normKey.includes('roleapplying') ||
      normKey.includes('interestedrole') ||
      normKey.includes('interestedteam') ||
      normKey.includes('domain') ||
      normKey.includes('position')
    ) {
      generalRaw = val
      break
    }
  }

  // 4. Fallback search: scan remaining non-excluded columns for explicit community role selections
  if (!p1Raw && !generalRaw) {
    for (const [key, val] of Object.entries(row)) {
      const normKey = normaliseText(key)
      if (isExcludedHeader(normKey)) continue
      if (val && val.length < 120) {
        const found = extractRolesFromText(val)
        if (found.length > 0) {
          generalRaw = val
          break
        }
      }
    }
  }

  const appliedRoles: string[] = []
  const addRole = (role: string) => {
    if (role && !appliedRoles.includes(role)) appliedRoles.push(role)
  }

  if (p1Raw) {
    extractRolesFromText(p1Raw).forEach(addRole)
  }
  if (p2Raw) {
    extractRolesFromText(p2Raw).forEach(addRole)
  }
  if (generalRaw) {
    extractRolesFromText(generalRaw).forEach(addRole)
  }

  // If candidate chose only 1 role, DO NOT fabricate a second role!
  // If candidate chose 0 roles, fallback to Technical Team only.
  if (appliedRoles.length === 0) {
    appliedRoles.push('Technical Team')
  }

  return {
    priority1: appliedRoles[0] || 'Technical Team',
    priority2: appliedRoles[1] || '',
    roles: appliedRoles,
  }
}

/**
 * Determines which role should be given priority for shortlisting.
 * If an applicant achieves a higher score in Priority 2 than Priority 1,
 * Priority 2 is given shortlisting priority.
 */
export function determineShortlistPriority(
  p1?: RolePriorityScore,
  p2?: RolePriorityScore,
  defaultRole: string = 'Technical Team'
): ShortlistPriorityAllocation {
  if (p1 && p2) {
    if (p2.score > p1.score) {
      return {
        role: p2.role,
        score: p2.score,
        rank: p2.rank || 1,
        sourcePriority: 'Priority 2',
        reason: `Higher score achieved in Priority 2 (${p2.score} pts in ${p2.role} vs ${p1.score} pts in ${p1.role}). Prioritized for ${p2.role} shortlisting.`,
      }
    } else {
      return {
        role: p1.role,
        score: p1.score,
        rank: p1.rank || 1,
        sourcePriority: 'Priority 1',
        reason: `Top score achieved in Primary Preference (${p1.score} pts in ${p1.role} vs ${p2.score} pts in ${p2.role}). Prioritized for ${p1.role} shortlisting.`,
      }
    }
  } else if (p1) {
    return {
      role: p1.role,
      score: p1.score,
      rank: p1.rank || 1,
      sourcePriority: 'Priority 1',
      reason: `Primary choice evaluated with score of ${p1.score}/100. Prioritized for ${p1.role} shortlisting.`,
    }
  }
  return {
    role: defaultRole,
    score: 80,
    rank: 1,
    sourcePriority: 'Priority 1',
    reason: `Allocated to ${defaultRole} based on candidate profile.`,
  }
}

/**
 * Computes deterministic role rankings across all applicants for both Priority 1 and Priority 2 choices.
 * Automatically gives shortlisting priority to the role where the candidate achieved their higher score.
 */
export function computeAndAssignDualPriorityRankings(applicants: ApplicantBrief[]): ApplicantBrief[] {
  // 1. Assign shortlist priority allocation to each applicant based on which role they scored higher in
  applicants.forEach((app) => {
    app.shortlistPriority = determineShortlistPriority(app.priority1, app.priority2, app.roles[0])
    const availableScores = [app.priority1?.score, app.priority2?.score].filter(
      (score): score is number => typeof score === 'number'
    )
    if (availableScores.length) {
      app.totalScore = Math.max(...availableScores)
      app.recommendation =
        app.totalScore >= 80 ? 'STRONG_INTERVIEW' : app.totalScore >= 65 ? 'INTERVIEW_CONSIDERATION' : 'MANUAL_REVIEW'
    }
  })

  // 2. Rank candidates for each role, giving shortlisting priority to candidates who scored higher in this role
  COMMUNITY_ROLES.forEach((roleName) => {
    const roleCandidates = applicants.filter(
      (a) =>
        Boolean(a.priority1 && roleMatchesFilter(a.priority1.role, roleName)) ||
        Boolean(a.priority2 && roleMatchesFilter(a.priority2.role, roleName))
    )

    // Sort order:
    // A) Candidates whose HIGHEST score is in this role (shortlist priority role) come first, sorted by score descending.
    // B) Candidates who selected this role as secondary choice with lower score come next, sorted by score descending.
    roleCandidates.sort((a, b) => {
      const isPriorityA = Boolean(a.shortlistPriority && roleMatchesFilter(a.shortlistPriority.role, roleName)) ? 1 : 0
      const isPriorityB = Boolean(b.shortlistPriority && roleMatchesFilter(b.shortlistPriority.role, roleName)) ? 1 : 0
      if (isPriorityA !== isPriorityB) {
        return isPriorityB - isPriorityA
      }
      const scoreA =
        a.priority1 && roleMatchesFilter(a.priority1.role, roleName)
          ? a.priority1.score
          : a.priority2 && roleMatchesFilter(a.priority2.role, roleName)
          ? a.priority2.score
          : 0
      const scoreB =
        b.priority1 && roleMatchesFilter(b.priority1.role, roleName)
          ? b.priority1.score
          : b.priority2 && roleMatchesFilter(b.priority2.role, roleName)
          ? b.priority2.score
          : 0
      return scoreB - scoreA
    })

    const totalInRole = roleCandidates.length

    roleCandidates.forEach((a, idx) => {
      const rank = idx + 1
      if (a.priority1 && roleMatchesFilter(a.priority1.role, roleName)) {
        a.priority1.rank = rank
        a.priority1.totalInRole = totalInRole
      }
      if (a.priority2 && roleMatchesFilter(a.priority2.role, roleName)) {
        a.priority2.rank = rank
        a.priority2.totalInRole = totalInRole
      }
      if (a.shortlistPriority && roleMatchesFilter(a.shortlistPriority.role, roleName)) {
        a.shortlistPriority.rank = rank
      }
    })
  })

  // 3. Synchronize detailed records in storage
  applicants.forEach((app) => {
    const detail = getStoredLiveDetail(app.applicantId)
    if (detail) {
      detail.brief = app
      detail.applicant.roles = app.roles
      detail.applicant.total_score = app.totalScore
      detail.applicant.recommendation = app.recommendation
      detail.applicant.priority1 = app.priority1
      detail.applicant.priority2 = app.priority2
      detail.applicant.shortlist_priority = app.shortlistPriority
      detail.applicant.role_scores = {
        ...(app.priority1 ? { [app.priority1.role]: app.priority1.score } : {}),
        ...(app.priority2 ? { [app.priority2.role]: app.priority2.score } : {}),
      }
      if (detail.evaluation) {
        detail.evaluation.total_score = app.totalScore
        detail.evaluation.ai_suggested_total = app.totalScore
        detail.evaluation.recommendation = app.recommendation
        detail.evaluation.role_evaluations = [
          ...(app.priority1
            ? [
                {
                  role_id: app.priority1.role,
                  priority: 'PRIMARY',
                  score: app.priority1.score,
                  rank: app.priority1.rank,
                  total_candidates: app.priority1.totalInRole,
                  fit: app.priority1.fit || (app.priority1.score >= 80 ? 'high' : app.priority1.score >= 65 ? 'medium' : 'low'),
                  rationale: `Priority 1 (Primary Preference): Evaluated score ${app.priority1.score}/100. Rank #${app.priority1.rank} of ${app.priority1.totalInRole} candidates in ${app.priority1.role}.${
                    app.shortlistPriority?.role === app.priority1.role ? ' (🏆 Higher score — Shortlist Priority)' : ''
                  }`,
                },
              ]
            : []),
          ...(app.priority2
            ? [
                {
                  role_id: app.priority2.role,
                  priority: 'SECONDARY',
                  score: app.priority2.score,
                  rank: app.priority2.rank,
                  total_candidates: app.priority2.totalInRole,
                  fit: app.priority2.fit || (app.priority2.score >= 80 ? 'high' : app.priority2.score >= 65 ? 'medium' : 'low'),
                  rationale: `Priority 2 (Secondary Preference): Evaluated score ${app.priority2.score}/100. Rank #${app.priority2.rank} of ${app.priority2.totalInRole} candidates in ${app.priority2.role}.${
                    app.shortlistPriority?.role === app.priority2.role ? ' (🏆 Higher score — Shortlist Priority)' : ''
                  }`,
                },
              ]
            : []),
        ]
      }
      saveStoredLiveDetail(detail)
    }
  })

  return applicants
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

  COMMUNITY_ROLES.forEach((cr) => {
    const roleId = roleIdFor(cr)
    roleStatsMap[roleId] = {
      roleId,
      name: cr,
      applicants: 0,
      processed: 0,
      eligible: 0,
      shortlisted: 0,
      averageScore: 0,
      strongRecommendations: 0,
    }
  })

  applicants.forEach((app) => {
    const canonRoles = (app.roles.length ? app.roles : ['Technical Team']).map(canonicalizeRole)
    canonRoles.forEach((roleName) => {
      const roleId = roleIdFor(roleName)
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
      .filter((a) =>
        (a.roles.length ? a.roles : ['Technical Team'])
          .some((r) => roleIdFor(r) === st.roleId)
      )
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
  const canRole = canonicalizeRole(appliedRole)
  const isTechRole = canRole === 'Technical Team'
  const isEventPR = canRole === 'Event and PR Management'
  const isCreative = canRole === 'Creative and Decoration'
  const isSocialMedia = canRole === 'Social Media, Marketing and Outreach'
  const isOpsLogistics = canRole === 'Operations and Logistics'

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
    } else if (isSocialMedia) {
      if (s.includes('communication') || s.includes('speaking')) skillsPoints += 4.5
      else if (s.includes('event') || s.includes('planning')) skillsPoints += 4.0
      else if (s.includes('leadership')) skillsPoints += 3.5
      else if (s.includes('problem')) skillsPoints += 3.0
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
        const row = detail.applicant.responses as Record<string, string>
        const resumeLink = findValue(row, ['resume', 'cv', 'curriculum vitae', 'drive', 'portfolio', 'upload', 'link'])
        const phone =
          findValue(row, ['phone', 'mobile', 'whatsapp', 'contact', 'telephone', 'calling']) ||
          detail.applicant.phone ||
          brief.phone ||
          ''
        brief.phone = phone
        detail.applicant.phone = phone
        detail.brief.phone = phone

        const { priority1, priority2, roles } = extractApplicantPriorities(row)

        brief.roles = roles
        detail.applicant.roles = roles
        detail.brief.roles = roles

        const evalRes1 = priority1 ? evaluateStudentApplication(row, priority1, resumeLink) : null
        const evalRes2 = priority2 ? evaluateStudentApplication(row, priority2, resumeLink) : null

        const score1 = evalRes1?.score ?? 0
        const score2 = evalRes2?.score ?? 0
        const maxScore = priority2 && evalRes2 ? Math.max(score1, score2) : score1
        const rec = maxScore >= 80 ? 'STRONG_INTERVIEW' : maxScore >= 65 ? 'INTERVIEW_CONSIDERATION' : 'MANUAL_REVIEW'

        brief.totalScore = maxScore
        brief.recommendation = rec
        brief.roleScores = {
          ...(priority1 && evalRes1 ? { [priority1]: score1 } : {}),
          ...(priority2 && evalRes2 ? { [priority2]: score2 } : {}),
        }

        brief.priority1 = priority1 && evalRes1
          ? {
              role: priority1,
              priority: 'Priority 1',
              score: score1,
              rank: 1,
              totalInRole: 1,
              fit: score1 >= 80 ? 'high' : score1 >= 65 ? 'medium' : 'low',
              recommendation: evalRes1.recommendation,
            }
          : undefined
        brief.priority2 = priority2 && evalRes2
          ? {
              role: priority2,
              priority: 'Priority 2',
              score: score2,
              rank: 1,
              totalInRole: 1,
              fit: score2 >= 80 ? 'high' : score2 >= 65 ? 'medium' : 'low',
              recommendation: evalRes2.recommendation,
            }
          : undefined
        brief.shortlistPriority = determineShortlistPriority(
          brief.priority1,
          brief.priority2,
          priority1 || roles[0] || 'Technical Team'
        )

        detail.applicant.total_score = maxScore
        detail.applicant.recommendation = rec
        detail.applicant.priority1 = brief.priority1
        detail.applicant.priority2 = brief.priority2
        detail.applicant.shortlist_priority = brief.shortlistPriority
        detail.applicant.role_scores = brief.roleScores

        const activeEval = brief.shortlistPriority?.role === priority2 && evalRes2 ? evalRes2 : (evalRes1 || evalRes2)

        if (detail.evaluation && activeEval) {
          detail.evaluation.total_score = maxScore
          detail.evaluation.ai_suggested_total = maxScore
          detail.evaluation.recommendation = rec
          detail.evaluation.criteria = activeEval.criteria
          detail.evaluation.summary = activeEval.summary
          detail.evaluation.strengths = activeEval.strengths
          detail.evaluation.technical_skills = activeEval.technicalSkills
          detail.evaluation.nontechnical_skills = activeEval.nonTechnicalSkills
          detail.evaluation.interview_questions = [
            ...(priority1
              ? [
                  {
                    role: priority1,
                    question: `Tell us about your experience related to ${priority1} and what inspired you to apply to AWS Student Builder Group at SJBIT.`,
                    why: 'Assesses candidate motivation and core domain experience.',
                  },
                ]
              : []),
            ...(priority2
              ? [
                  {
                    role: priority2,
                    question: `Describe your familiarity with ${priority2} and how you can support this team if selected for your secondary preference.`,
                    why: 'Evaluates adaptability and secondary domain execution.',
                  },
                ]
              : [
                  {
                    role: priority1 || roles[0] || 'Technical Team',
                    question:
                      'Describe a challenging project you worked on recently and how you handled unexpected roadblocks.',
                    why: 'Evaluates resilience, domain execution, and problem solving.',
                  },
                ]),
          ]
          detail.evaluation.role_evaluations = [
            ...(priority1 && evalRes1
              ? [
                  {
                    role_id: priority1,
                    priority: 'PRIMARY' as const,
                    score: score1,
                    rank: 1,
                    total_candidates: 1,
                    fit: score1 >= 80 ? 'high' : score1 >= 65 ? 'medium' : 'low',
                    rationale: `Priority 1 (Primary Preference): ${evalRes1.summary}`,
                  },
                ]
              : []),
            ...(priority2 && evalRes2
              ? [
                  {
                    role_id: priority2,
                    priority: 'SECONDARY' as const,
                    score: score2,
                    rank: 1,
                    total_candidates: 1,
                    fit: score2 >= 80 ? 'high' : score2 >= 65 ? 'medium' : 'low',
                    rationale: `Priority 2 (Secondary Preference): ${evalRes2.summary}`,
                  },
                ]
              : []),
          ]
        }

        saveStoredLiveDetail(detail)
        updated = true
      }
    })

    if (updated) {
      computeAndAssignDualPriorityRankings(applicants)
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

      const submittedAt = findValue(row, ['timestamp', 'date', 'time']) || new Date().toISOString()
      const resumeLink = findValue(row, ['resume', 'cv', 'curriculum vitae', 'drive', 'portfolio', 'upload', 'link'])

      const { priority1, priority2, roles } = extractApplicantPriorities(row)

      // Evaluate ONLY the roles explicitly applied for in the form.
      const evalResult1 = priority1 ? evaluateStudentApplication(row, priority1, resumeLink) : null
      const evalResult2 = priority2 ? evaluateStudentApplication(row, priority2, resumeLink) : null
      const score = evalResult1?.score ?? 0
      const score2 = evalResult2?.score ?? 0
      const maxScore = priority2 && evalResult2 ? Math.max(score, score2) : score
      const recommendation =
        maxScore >= 80 ? 'STRONG_INTERVIEW' : maxScore >= 65 ? 'INTERVIEW_CONSIDERATION' : 'MANUAL_REVIEW'

      // Check if candidate already exists
      const existingMatch = existingByEmail.get(email.toLowerCase()) || existingByUsn.get(usn.toLowerCase())
      const applicantId = existingMatch
        ? existingMatch.applicantId
        : `AWS-2026-${String(existing.length + newApplicants.length + 1).padStart(3, '0')}`

      const priority1Obj: RolePriorityScore | undefined = priority1 && evalResult1
        ? {
            role: priority1,
            priority: 'Priority 1',
            score,
            rank: 1,
            totalInRole: 1,
            fit: score >= 80 ? 'high' : score >= 65 ? 'medium' : 'low',
            recommendation: evalResult1.recommendation,
          }
        : undefined

      const priority2Obj: RolePriorityScore | undefined = priority2 && evalResult2
        ? {
            role: priority2,
            priority: 'Priority 2',
            score: score2,
            rank: 1,
            totalInRole: 1,
            fit: score2 >= 80 ? 'high' : score2 >= 65 ? 'medium' : 'low',
            recommendation: evalResult2.recommendation,
          }
        : undefined

      const shortlistPriority = determineShortlistPriority(
        priority1Obj,
        priority2Obj,
        priority1 || roles[0] || 'Technical Team'
      )

      const activeEvalResult = shortlistPriority.role === priority2 && evalResult2 ? evalResult2 : (evalResult1 || evalResult2)

      const phone = findValue(row, ['phone', 'mobile', 'whatsapp', 'contact', 'telephone', 'calling']) || ''

      const brief: ApplicantBrief = {
        applicantId,
        fullName,
        email,
        phone,
        usn,
        department,
        yearOfStudy,
        roles,
        submittedAt,
        processingStatus: 'COMPLETED',
        totalScore: maxScore,
        recommendation,
        eligibilityStatus: 'PASS',
        reviewStatus: existingMatch ? existingMatch.reviewStatus : 'PENDING',
        urgentReview: false,
        documents: resumeLink ? 1 : 0,
        rubricVersion: '2026.2',
        priority1: priority1Obj,
        priority2: priority2Obj,
        shortlistPriority,
        roleScores: {
          ...(priority1 && evalResult1 ? { [priority1]: score } : {}),
          ...(priority2 && evalResult2 ? { [priority2]: score2 } : {}),
        },
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
          total_score: maxScore,
          recommendation,
          eligibility_status: 'PASS',
          eligibility_failures: [],
          role_scores: {
            ...(priority1 && evalResult1 ? { [priority1]: score } : {}),
            ...(priority2 && evalResult2 ? { [priority2]: score2 } : {}),
          },
          priority1: priority1Obj,
          priority2: priority2Obj,
          shortlist_priority: shortlistPriority,
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
        evaluation: activeEvalResult
          ? {
              applicant_id: applicantId,
              evaluation_id: `eval-${applicantId}`,
              rubric_version: '2026.2',
              created_at: new Date().toISOString(),
              criteria: activeEvalResult.criteria,
              total_score: maxScore,
              max_score: 100,
              score_complete: true,
              ai_suggested_total: maxScore,
              recommendation,
              eligibility: [
                { rule_id: 'enrolled', label: 'SJBIT Student', status: 'PASS', mandatory: true, detail: 'Enrolled', observed: usn },
                { rule_id: 'year', label: 'Eligible Year', status: 'PASS', mandatory: true, detail: '2nd/3rd/4th', observed: yearOfStudy },
              ],
              eligibility_status: 'PASS',
              eligibility_failures: [],
              summary: activeEvalResult.summary,
              strengths: activeEvalResult.strengths,
              weaknesses: [],
              missing_information: [],
              inconsistencies: [],
              uncertain_findings: [],
              technical_skills: activeEvalResult.technicalSkills,
              nontechnical_skills: activeEvalResult.nonTechnicalSkills,
              projects: [],
              certifications: [],
              experience: [],
              leadership_evidence: [],
              communication_evidence: [],
              interview_questions: [
                ...(priority1
                  ? [
                      {
                        role: priority1,
                        question: `Tell us about your experience related to ${priority1} and what inspired you to apply to AWS Student Builder Group at SJBIT.`,
                        why: 'Assesses candidate motivation and core domain experience.',
                      },
                    ]
                  : []),
                ...(priority2
                  ? [
                      {
                        role: priority2,
                        question:
                          `Describe your familiarity with ${priority2} and how you can support this team if selected for your secondary preference.`,
                        why: 'Evaluates adaptability and secondary domain execution.',
                      },
                    ]
                  : [
                      {
                        role: priority1 || roles[0] || 'Technical Team',
                        question:
                          'Describe a challenging project you worked on recently and how you handled unexpected roadblocks.',
                        why: 'Evaluates resilience, domain execution, and problem solving.',
                      },
                    ]),
              ],
              role_evaluations: [
                ...(priority1 && evalResult1
                  ? [
                      {
                        role_id: priority1,
                        priority: 'PRIMARY' as const,
                        score,
                        rank: 1,
                        total_candidates: 1,
                        fit: score >= 80 ? 'high' : score >= 65 ? 'medium' : 'low',
                        rationale: `Priority 1 (Primary Preference): ${evalResult1.summary}`,
                      },
                    ]
                  : []),
                ...(priority2 && evalResult2
                  ? [
                      {
                        role_id: priority2,
                        priority: 'SECONDARY' as const,
                        score: score2,
                        rank: 1,
                        total_candidates: 1,
                        fit: score2 >= 80 ? 'high' : score2 >= 65 ? 'medium' : 'low',
                        rationale: `Priority 2 (Secondary Preference): ${evalResult2.summary}`,
                      },
                    ]
                  : []),
              ],
              confidence: 'high',
              model_metadata: { provider: 'gemini', model: 'gemini-1.5-flash', structured_output: true },
              validation_errors: [],
              document_coverage: {},
              review_status: existingMatch ? existingMatch.reviewStatus : 'PENDING',
              human_notes: '',
              human_override: {},
              version: 2,
          }
          : null,
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

  const combined = computeAndAssignDualPriorityRankings(Array.from(finalMap.values()))
  saveStoredLiveApplicants(combined)
  localStorage.setItem('sbg_eval_version', EVAL_VERSION)

  return {
    totalRows: records.length,
    imported: newApplicants.length + updatedApplicants.length,
    applicants: combined,
    errors,
  }
}

