import { getValidToken, refreshSession } from './auth'
import {
  getMockApplicantDetail,
  getMockApplicantsList,
  getMockOverview,
  getMockShortlist,
  mockReportsList,
  mockSettings,
} from './mockData'
import { importGoogleFormResponses, parseCSV } from './googleSync'
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
  if (path.startsWith('/intake/sync-sheet')) {
    return { total_rows: 0, imported: 0, skipped_duplicates: 0, message: 'Synced' } as unknown as T
  }
  if (path.startsWith('/applicants/') && path.includes('/review')) {
    const b = (body as Record<string, string>) || {}
    return { applicantId: 'AWS-2026-001', reviewStatus: b.decision || 'APPROVED', decision: b.decision || 'APPROVED' } as unknown as T
  }
  if (path.startsWith('/applicants/') && path.includes('/url')) {
    return { url: '#', filename: 'Resume.pdf', expiresInSeconds: 900 } as unknown as T
  }
  if (path.startsWith('/applicants/')) {
    const id = decodeURIComponent(path.replace('/applicants/', '').split('/')[0])
    return getMockApplicantDetail(id) as unknown as T
  }
  if (path.startsWith('/applicants')) {
    const items = getMockApplicantsList()
    return {
      items,
      nextCursor: null,
      pageSize: 25,
      count: items.length,
    } as unknown as T
  }
  if (path.startsWith('/shortlist/bulk')) {
    const b = (body as { applicantIds?: string[]; decision?: string }) || {}
    return { updated: b.applicantIds || [], skipped: [], decision: b.decision || 'APPROVED' } as unknown as T
  }
  if (path.startsWith('/shortlist')) return getMockShortlist() as unknown as T
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

  shortlist: (params: { role?: string; minScore?: number; maxScore?: number; limit?: number } = {}) =>
    request<ShortlistResponse>(`/shortlist${query(params)}`),

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
