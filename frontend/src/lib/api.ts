import { getValidToken, refreshSession } from './auth'
import type {
  AdminList,
  ApplicantDetail,
  Overview,
  PagedApplicants,
  ReportRecord,
  SettingsPayload,
  ShortlistResponse,
} from '../types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')

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

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth) {
    const token = await getValidToken()
    if (token && token !== 'local-dev-token') headers.Authorization = `Bearer ${token}`
  }

  let response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })

  if (response.status === 401 && auth) {
    const refreshed = await refreshSession()
    if (refreshed) {
      headers.Authorization = `Bearer ${refreshed.idToken}`
      response = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      })
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

  if (!response.ok) {
    const error = (payload as { error?: { message?: string; code?: string; details?: unknown } })?.error
    throw new ApiError(
      error?.message ?? `Request failed with status ${response.status}`,
      response.status,
      error?.code ?? 'API_ERROR',
      error?.details,
    )
  }
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
}
