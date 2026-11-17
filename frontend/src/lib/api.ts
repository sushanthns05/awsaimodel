import { getValidToken, refreshSession } from './auth'
import {
  getMockApplicantDetail,
  getMockApplicantsList,
  getMockOverview,
  mockReportsList,
  mockSettings,
} from './mockData'
import {
  importGoogleFormResponses,
  parseCSV,
  getStoredLiveDetail,
  saveStoredLiveDetail,
  getStoredLiveApplicants,
  saveStoredLiveApplicants,
  canonicalizeRole,
  roleMatchesFilter,
} from './googleSync'
import type {
  AdminList,
  ApplicantDetail,
  Overview,
  PagedApplicants,
  ReportRecord,
  SettingsPayload,
  ShortlistResponse,
} from '../types'

export function getApiBase(): string {
  if (typeof window !== 'undefined') {
    const custom = localStorage.getItem('sbg_api_base_url')
    if (custom) return custom.replace(/\/$/, '')
  }
  return (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')
}

export function setApiBaseUrl(url: string): void {
  if (typeof window !== 'undefined') {
    if (url) {
      localStorage.setItem('sbg_api_base_url', url.replace(/\/$/, ''))
    } else {
      localStorage.removeItem('sbg_api_base_url')
    }
  }
}

let _isDemoMode = false

export function isUsingDemoFallback(): boolean {
  return _isDemoMode
}

export class ApiError extends Error {
  status: number
  code: string
  details?: unknown
  constructor(message: string, status: number, code = 'API_ERROR', details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  auth?: boolean
  signal?: AbortSignal
}

function resolveFallback<T>(path: string, _method = 'GET', body?: unknown): T | undefined {
  _isDemoMode = true
  if (path.startsWith('/dashboard/overview')) return getMockOverview() as unknown as T

  if (path.startsWith('/intake/upload-csv')) {
    const b = (body as { csv_text?: string }) || {}
    const records = parseCSV(b.csv_text || '')
    const result = importGoogleFormResponses(records)
    return { total_rows: result.totalRows, imported: result.imported, skipped_duplicates: 0 } as unknown as T
  }

  // Handle manual score override
  if (path.startsWith('/applicants/') && path.includes('/evaluation')) {
    const id = decodeURIComponent(path.replace('/applicants/', '').split('/')[0])
    const b = (body as { scores?: Record<string, number>; reason?: string }) || {}
    const scores = b.scores || {}
    const detail = getStoredLiveDetail(id)
    if (detail && detail.evaluation) {
      let total = 0
      detail.evaluation.criteria.forEach((crit) => {
        if (scores[crit.criterion_id] !== undefined) {
          const val = Number(scores[crit.criterion_id])
          crit.final_score = Math.min(crit.max_score, Math.max(0, val))
          crit.suggested_score = crit.final_score
        }
        total += crit.final_score
      })
      total = Math.min(100, Math.max(0, Math.round(total * 10) / 10))
      const rec = total >= 80 ? 'STRONG_INTERVIEW' : total >= 65 ? 'INTERVIEW_CONSIDERATION' : 'MANUAL_REVIEW'

      detail.evaluation.total_score = total
      detail.evaluation.ai_suggested_total = total
      detail.evaluation.recommendation = rec
      detail.evaluation.human_notes = b.reason || 'Manually corrected criterion scores'
      detail.applicant.total_score = total
      detail.applicant.recommendation = rec
      detail.applicant.role_scores = { [canonicalizeRole(detail.applicant.roles[0])]: total }
      detail.brief.totalScore = total
      detail.brief.recommendation = rec

      detail.audit.push({
        audit_id: `aud-${Date.now()}`,
        applicant_id: id,
        reviewer: 'admin@sjbit.edu.in',
        action: 'MANUAL_SCORE_OVERRIDE',
        timestamp: new Date().toISOString(),
        previous_value: detail.evaluation.total_score,
        updated_value: total,
        reason: b.reason || 'Manual score correction',
        metadata: { scores, totalScore: total },
      })
      detail.evaluationHistory.push({
        evaluationId: `override-${Date.now()}`,
        totalScore: total,
        recommendation: rec,
        createdAt: new Date().toISOString(),
        rubricVersion: detail.evaluation.rubric_version || '2026.2',
        reviewStatus: detail.applicant.review_status || 'PENDING',
        scoreComplete: true,
        model: 'manual-override',
        validationErrors: [],
        humanOverride: { scores, totalScore: total, reason: b.reason || 'Manual score correction' },
      })

      saveStoredLiveDetail(detail)

      const all = getStoredLiveApplicants()
      const match = all.find((a) => a.applicantId === id)
      if (match) {
        match.totalScore = total
        match.recommendation = rec
        saveStoredLiveApplicants(all)
      }

      return { applicantId: id, totalScore: total, recommendation: rec } as unknown as T
    }
    return { applicantId: id, totalScore: 0, recommendation: 'MANUAL_REVIEW' } as unknown as T
  }

  // Handle single applicant review decision
  if (path.startsWith('/applicants/') && path.includes('/review')) {
    const id = decodeURIComponent(path.replace('/applicants/', '').split('/')[0])
    const b = (body as Record<string, string>) || {}
    const decision = b.decision || 'APPROVED'
    const status = decision === 'SHORTLISTED' || decision === 'APPROVED' ? 'APPROVED' : decision === 'REJECTED' ? 'REJECTED' : 'PENDING'

    const detail = getStoredLiveDetail(id)
    if (detail) {
      detail.brief.reviewStatus = status
      detail.applicant.review_status = status
      detail.applicant.review_decision = decision
      detail.applicant.review_notes = b.notes || b.reason || ''
      detail.applicant.reviewed_by = 'admin@sjbit.edu.in'
      if (detail.evaluation) {
        detail.evaluation.review_status = status
        detail.evaluation.human_notes = b.notes || b.reason || ''
      }
      detail.audit.push({
        audit_id: `aud-${Date.now()}`,
        applicant_id: id,
        reviewer: 'admin@sjbit.edu.in',
        action: 'HUMAN_REVIEW',
        timestamp: new Date().toISOString(),
        previous_value: detail.applicant.review_status,
        updated_value: status,
        reason: b.notes || b.reason || '',
        metadata: { decision, notes: b.notes },
      })
      saveStoredLiveDetail(detail)
    }

    const all = getStoredLiveApplicants()
    const match = all.find((a) => a.applicantId === id)
    if (match) {
      match.reviewStatus = status
      saveStoredLiveApplicants(all)
    }

    return { applicantId: id, reviewStatus: status, decision } as unknown as T
  }

  if (path.startsWith('/applicants/') && path.includes('/url')) {
    const id = decodeURIComponent(path.replace('/applicants/', '').split('/')[0])
    const detail = getStoredLiveDetail(id)
    const dl = detail?.documents?.[0]?.downloadUrl
    return { url: dl || '#', filename: 'Resume.pdf', expiresInSeconds: 900 } as unknown as T
  }

  if (path.startsWith('/applicants/')) {
    const id = decodeURIComponent(path.replace('/applicants/', '').split('/')[0])
    return getMockApplicantDetail(id) as unknown as T
  }

  // Handle applicants directory with full real-time filtering and sorting
  if (path.startsWith('/applicants?') || path === '/applicants') {
    let items = getMockApplicantsList()

    const queryPart = path.includes('?') ? path.split('?')[1] : ''
    const params = new URLSearchParams(queryPart)

    const q = params.get('q')?.toLowerCase().trim() || ''
    const role = params.get('role')?.toLowerCase().trim() || ''
    const status = params.get('status')?.trim() || ''
    const eligibility = params.get('eligibility')?.trim() || ''
    const recommendation = params.get('recommendation')?.trim() || ''
    const reviewStatus = params.get('reviewStatus')?.trim() || ''
    const minScore = params.has('minScore') && params.get('minScore') !== '' ? Number(params.get('minScore')) : null
    const maxScore = params.has('maxScore') && params.get('maxScore') !== '' ? Number(params.get('maxScore')) : null
    const sort = params.get('sort') || 'submitted_at'
    const pageSize = Number(params.get('pageSize')) || 25

    if (q) {
      items = items.filter(
        (a) =>
          a.fullName.toLowerCase().includes(q) ||
          a.email.toLowerCase().includes(q) ||
          a.usn.toLowerCase().includes(q) ||
          a.department.toLowerCase().includes(q) ||
          a.roles.some((r) => r.toLowerCase().includes(q))
      )
    }

    if (role && role !== 'all') {
      items = items.filter((a) => a.roles.some((r) => roleMatchesFilter(r, role)))
    }

    if (status) {
      items = items.filter((a) => a.processingStatus === status)
    }

    if (eligibility) {
      items = items.filter((a) => a.eligibilityStatus === eligibility)
    }

    if (recommendation) {
      items = items.filter((a) => a.recommendation === recommendation)
    }

    if (reviewStatus) {
      items = items.filter((a) => a.reviewStatus === reviewStatus)
    }

    if (minScore !== null && !isNaN(minScore)) {
      items = items.filter((a) => a.totalScore >= minScore)
    }

    if (maxScore !== null && !isNaN(maxScore)) {
      items = items.filter((a) => a.totalScore <= maxScore)
    }

    if (sort === 'score_desc' || sort === 'totalScore') {
      items.sort((a, b) => b.totalScore - a.totalScore)
    } else if (sort === 'score_asc') {
      items.sort((a, b) => a.totalScore - b.totalScore)
    } else if (sort === 'name_asc') {
      items.sort((a, b) => a.fullName.localeCompare(b.fullName))
    } else {
      items.sort((a, b) => {
        const da = new Date(a.submittedAt).getTime() || 0
        const db = new Date(b.submittedAt).getTime() || 0
        return db - da
      })
    }

    return {
      items,
      nextCursor: null,
      pageSize,
      count: items.length,
    } as unknown as T
  }

  // Handle bulk shortlist decisions
  if (path.startsWith('/shortlist/bulk')) {
    const b = (body as { applicantIds?: string[]; decision?: string; notes?: string; reason?: string }) || {}
    const ids = new Set(b.applicantIds || [])
    const dec = b.decision || 'APPROVED'
    const status = dec === 'SHORTLISTED' || dec === 'APPROVED' ? 'APPROVED' : dec === 'REJECTED' ? 'REJECTED' : 'PENDING'

    const all = getStoredLiveApplicants()
    all.forEach((app) => {
      if (ids.has(app.applicantId)) {
        app.reviewStatus = status as 'APPROVED' | 'REJECTED' | 'PENDING'
        const detail = getStoredLiveDetail(app.applicantId)
        if (detail) {
          detail.brief.reviewStatus = status as 'APPROVED' | 'REJECTED' | 'PENDING'
          detail.applicant.review_status = status as 'APPROVED' | 'REJECTED' | 'PENDING'
          detail.applicant.review_decision = dec
          detail.applicant.review_notes = b.notes || b.reason || ''
          detail.applicant.reviewed_by = 'admin@sjbit.edu.in'
          if (detail.evaluation) {
            detail.evaluation.review_status = status as 'APPROVED' | 'REJECTED' | 'PENDING'
            detail.evaluation.human_notes = b.notes || b.reason || ''
          }
          detail.audit.push({
            audit_id: `aud-${Date.now()}`,
            applicant_id: app.applicantId,
            reviewer: 'admin@sjbit.edu.in',
            action: 'BULK_DECISION',
            timestamp: new Date().toISOString(),
            previous_value: app.reviewStatus,
            updated_value: status,
            reason: b.reason || b.notes || '',
            metadata: { decision: dec, reason: b.reason },
          })
          saveStoredLiveDetail(detail)
        }
      }
    })
    saveStoredLiveApplicants(all)
    return { updated: Array.from(ids), skipped: [], decision: dec } as unknown as T
  }

  // Handle shortlist query with role, priority, minScore, maxScore
  if (path.startsWith('/shortlist?') || path === '/shortlist') {
    const queryPart = path.includes('?') ? path.split('?')[1] : ''
    const params = new URLSearchParams(queryPart)

    const role = params.get('role')?.toLowerCase().trim() || ''
    const priority = params.get('priority')?.trim() || '' // 'P1', 'P2', or ''
    const minScore = params.has('minScore') && params.get('minScore') !== '' ? Number(params.get('minScore')) : null
    const maxScore = params.has('maxScore') && params.get('maxScore') !== '' ? Number(params.get('maxScore')) : null
    const limit = Number(params.get('limit')) || 300

    let list = getStoredLiveApplicants()

    if (role && role !== 'all') {
      list = list.filter((a) => {
        const matchesP1 = Boolean(a.priority1 && roleMatchesFilter(a.priority1.role, role))
        const matchesP2 = Boolean(a.priority2 && roleMatchesFilter(a.priority2.role, role))

        if (priority === 'P1') return matchesP1
        if (priority === 'P2') return matchesP2
        return matchesP1 || matchesP2
      })
    }

    let items = list.map((app) => {
      let activeScore = app.totalScore
      let activeRank = 1
      let activePriority: 'Priority 1' | 'Priority 2' = 'Priority 1'

      if (role && role !== 'all') {
        const isP1 = Boolean(app.priority1 && roleMatchesFilter(app.priority1.role, role))
        const isP2 = Boolean(app.priority2 && roleMatchesFilter(app.priority2.role, role))

        if (priority === 'P2' && isP2) {
          activeScore = app.priority2?.score ?? app.totalScore
          activeRank = app.priority2?.rank ?? 1
          activePriority = 'Priority 2'
        } else if (isP1) {
          activeScore = app.priority1?.score ?? app.totalScore
          activeRank = app.priority1?.rank ?? 1
          activePriority = 'Priority 1'
        } else if (isP2) {
          activeScore = app.priority2?.score ?? app.totalScore
          activeRank = app.priority2?.rank ?? 1
          activePriority = 'Priority 2'
        }
      }

      return {
        applicantId: app.applicantId,
        fullName: app.fullName,
        email: app.email,
        usn: app.usn,
        department: app.department,
        yearOfStudy: app.yearOfStudy,
        roles: app.roles.map(canonicalizeRole),
        roleScore: activeScore,
        totalScore: app.totalScore,
        recommendation: app.recommendation,
        eligibilityStatus: app.eligibilityStatus,
        eligibilityFailures: [],
        reviewStatus: app.reviewStatus,
        reviewDecision: app.reviewStatus === 'APPROVED' ? 'SHORTLISTED' : app.reviewStatus === 'REJECTED' ? 'REJECTED' : 'PENDING',
        reviewedBy: '',
        strongestEvidence: [
          app.priority1 ? `P1: ${app.priority1.role} (Rank #${app.priority1.rank}, Score ${app.priority1.score})` : '',
          app.priority2 ? `P2: ${app.priority2.role} (Rank #${app.priority2.rank}, Score ${app.priority2.score})` : '',
        ].filter(Boolean),
        concerns: [],
        urgentReview: app.urgentReview,
        documents: app.documents,
        rank: activeRank,
        priority1: app.priority1,
        priority2: app.priority2,
        activeRolePriority: activePriority,
        shortlistPriority: app.shortlistPriority,
        isShortlistPriorityRole: Boolean(
          role && role !== 'all' && app.shortlistPriority && roleMatchesFilter(app.shortlistPriority.role, role)
        ),
      }
    })

    if (priority === 'SHORTLIST_PRIORITY') {
      items = items.filter((a) => a.isShortlistPriorityRole)
    }

    if (minScore !== null && !isNaN(minScore)) {
      items = items.filter((a) => a.roleScore >= minScore)
    }

    if (maxScore !== null && !isNaN(maxScore)) {
      items = items.filter((a) => a.roleScore <= maxScore)
    }

    // Sort order: candidates who achieved their HIGHER score in this role are prioritized for shortlisting!
    items.sort((a, b) => {
      if (role && role !== 'all') {
        const aPri = a.isShortlistPriorityRole ? 1 : 0
        const bPri = b.isShortlistPriorityRole ? 1 : 0
        if (aPri !== bPri) {
          return bPri - aPri
        }
      }
      return b.roleScore - a.roleScore
    })
    items.forEach((item, idx) => {
      item.rank = idx + 1
    })

    return {
      items: items.slice(0, limit),
      total: items.length,
      role: role || 'all',
      minScore,
      maxScore,
    } as unknown as T
  }
  if (path.startsWith('/reports/generate')) {
    return {
      report_id: `REP-${Date.now()}`,
      report_type: 'excel',
      title: 'Generated Matrix Report',
      created_at: new Date().toISOString(),
      created_by: 'admin@sjbit.edu.in',
      status: 'READY',
      download_url: '#',
      file_size_bytes: 52000,
      scope: {},
      downloadUrl: '#',
    } as unknown as T
  }
  if (path.startsWith('/reports')) return mockReportsList as unknown as T
  if (path.startsWith('/settings/ai/test')) {
    return { ok: true, message: 'Gemini multi-key rotation test successful (6 active keys in pool)', model: 'gemini-1.5-flash', latencyMs: 640 } as unknown as T
  }
  if (path.startsWith('/settings')) return mockSettings as unknown as T
  if (path.startsWith('/admins')) {
    return {
      admins: [
        { email: 'admin@sjbit.edu.in', group: 'sbg-admins', source: 'demo' },
        { email: 'reviewer@sjbit.edu.in', group: 'sbg-reviewers', source: 'demo' },
      ],
    } as unknown as T
  }
  if (path.startsWith('/me')) {
    return {
      user: {
        subject: 'admin',
        email: 'admin@sjbit.edu.in',
        groups: ['sbg-admins'],
        permissions: ['*'],
        isAdmin: true,
      },
    } as unknown as T
  }
  return undefined
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth) {
    const token = await getValidToken()
    if (token && token !== 'local-dev-token') headers.Authorization = `Bearer ${token}`
  }

  const apiBase = getApiBase()
  let response: Response

  try {
    response = await fetch(`${apiBase}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (err) {
    // Backend offline / CORS blocked - fallback to demo mock data
    const fallback = resolveFallback<T>(path, method, body)
    if (fallback !== undefined) return fallback
    throw new ApiError('Cannot reach recruitment backend API.', 503)
  }

  if (response.status === 401 && auth) {
    const refreshed = await refreshSession()
    if (refreshed) {
      headers.Authorization = `Bearer ${refreshed.idToken}`
      try {
        response = await fetch(`${apiBase}${path}`, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          signal,
        })
      } catch {
        const fallback = resolveFallback<T>(path, method, body)
        if (fallback !== undefined) return fallback
      }
    }
  }

  const text = await response.text()
  let payload: unknown = null

  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  // Handle case where static hosting rewrote API path to index.html (returns HTML with status 200)
  const isHtmlCatchall =
    typeof payload === 'string' &&
    (payload.trim().toLowerCase().startsWith('<!doctype') || payload.trim().toLowerCase().startsWith('<html'))

  if (isHtmlCatchall) {
    const fallback = resolveFallback<T>(path, method, body)
    if (fallback !== undefined) return fallback
    throw new ApiError(`Route ${path} did not return JSON. Verify backend is deployed.`, response.status || 502)
  }

  if (!response.ok) {
    const error = (payload as { error?: { message?: string; code?: string; details?: unknown } })?.error
    throw new ApiError(
      error?.message ?? `Request failed with status ${response.status}`,
      response.status,
      error?.code ?? 'API_ERROR',
      error?.details,
    )
  }

  _isDemoMode = false
  return payload as T
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  })
  const serialised = search.toString()
  return serialised ? `?${serialised}` : ''
}

export interface ApplicantFilters {
  q?: string
  role?: string
  status?: string
  eligibility?: string
  recommendation?: string
  reviewStatus?: string
  department?: string
  minScore?: number
  maxScore?: number
  urgent?: boolean
  sort?: string
  pageSize?: number
  cursor?: string
}

export const api = {
  me: () => request<{ user: { subject: string; email: string; groups: string[]; permissions: string[]; isAdmin: boolean } }>('/me'),

  overview: () => request<Overview>('/dashboard/overview'),

  applicants: (filters: ApplicantFilters = {}) =>
    request<PagedApplicants>(`/applicants${query({ ...filters })}`),

  applicant: (id: string) => request<ApplicantDetail>(`/applicants/${encodeURIComponent(id)}`),

  documentUrl: (id: string, documentId: string) =>
    request<{ url: string; filename: string; expiresInSeconds: number }>(
      `/applicants/${encodeURIComponent(id)}/documents/${encodeURIComponent(documentId)}/url`,
    ),

  review: (id: string, body: { decision: string; notes?: string; reason?: string }) =>
    request<{ applicantId: string; reviewStatus: string; decision: string }>(
      `/applicants/${encodeURIComponent(id)}/review`,
      { method: 'POST', body },
    ),

  overrideScores: (id: string, body: { scores: Record<string, number>; reason: string }) =>
    request<{ applicantId: string; totalScore: number; recommendation: string }>(
      `/applicants/${encodeURIComponent(id)}/evaluation`,
      { method: 'PATCH', body },
    ),

  reprocess: (id: string) =>
    request<{ applicantId: string; queue: Record<string, unknown>; processing?: Record<string, unknown> }>(
      `/applicants/${encodeURIComponent(id)}/reprocess`,
      { method: 'POST', body: {} },
    ),

  erase: (id: string, reason: string) =>
    request<{ applicantId: string; status: string }>(`/applicants/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      body: { reason },
    }),

  shortlist: (
    params: { role?: string; priority?: string; minScore?: number; maxScore?: number; limit?: number } = {}
  ) => request<ShortlistResponse>(`/shortlist${query(params)}`),

  bulkDecision: (body: { applicantIds: string[]; decision: string; notes?: string; reason?: string }) =>
    request<{ updated: string[]; skipped: { applicantId: string; reason: string }[]; decision: string }>(
      '/shortlist/bulk',
      { method: 'POST', body },
    ),

  reports: () => request<{ items: ReportRecord[]; count: number }>('/reports'),

  report: (id: string) => request<ReportRecord & { downloadUrl: string }>(`/reports/${encodeURIComponent(id)}`),

  generateReport: (body: { type: string; scope?: { role?: string; applicant_id?: string }; role?: string; applicantId?: string }) =>
    request<ReportRecord & { downloadUrl: string }>('/reports/generate', { method: 'POST', body }),

  reportDownload: (id: string) =>
    request<{ url: string; filename: string }>(`/reports/${encodeURIComponent(id)}/download`),

  settings: () => request<SettingsPayload>('/settings'),

  updateSettings: (key: string, value: Record<string, unknown>) =>
    request<{ key: string; version: number; value: Record<string, unknown> }>(`/settings/${key}`, {
      method: 'PUT',
      body: value,
    }),

  testAi: () => request<{ ok: boolean; message: string; model?: string; latencyMs?: number }>('/settings/ai/test', { method: 'POST', body: {} }),

  admins: () => request<AdminList>('/admins'),

  addAdmin: (body: { email: string; group: string }) =>
    request<{ status: string; email: string; group: string }>('/admins', { method: 'POST', body }),

  removeAdmin: (body: { email: string; group: string }) =>
    request<{ status: string; email: string; group: string }>('/admins', { method: 'DELETE', body }),

  syncGoogleSheet: (sheetUrl: string) =>
    request<{ total_rows: number; imported: number; skipped_duplicates: number }>('/intake/sync-sheet', {
      method: 'POST',
      body: { sheet_url: sheetUrl },
    }),

  importCsvResponses: (csvText: string) =>
    request<{ total_rows: number; imported: number; skipped_duplicates: number }>('/intake/upload-csv', {
      method: 'POST',
      body: { csv_text: csvText },
    }),
}
