import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from './api'
import type { PagedApplicants } from '../types'

const SESSION_KEY = 'sbg.recruitment.session'

function session() {
  return {
    idToken: 'test-token',
    accessToken: 'test-access-token',
    refreshToken: '',
    expiresAt: Date.now() + 60 * 60 * 1000,
    email: 'reviewer@sjbit.edu.in',
    groups: ['sbg-reviewers'],
  }
}

function response(status: number, body: unknown): Response {
  const text = typeof body === 'string' ? body : JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => text,
  } as Response
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session()))
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

describe('api client', () => {
  it('sends the bearer token and parses JSON', async () => {
    fetchMock.mockResolvedValue(response(200, { items: [], count: 0 }))

    const result = await api.applicants()

    expect(result).toEqual({ items: [], count: 0 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/applicants')
    expect(init.method).toBe('GET')
    expect(init.headers.Authorization).toBe('Bearer test-token')
    expect(init.body).toBeUndefined()
  })

  it('serialises query filters and omits empty values', async () => {
    fetchMock.mockResolvedValue(response(200, { items: [], count: 0 } as unknown as PagedApplicants))

    await api.applicants({ q: 'asha rao', role: 'technical_team', minScore: 50, status: '', pageSize: 25 })

    const url = fetchMock.mock.calls[0][0] as string
    const parsed = new URL(url, 'http://localhost')
    expect(parsed.pathname).toBe('/api/applicants')
    expect(parsed.searchParams.get('q')).toBe('asha rao')
    expect(parsed.searchParams.get('role')).toBe('technical_team')
    expect(parsed.searchParams.get('minScore')).toBe('50')
    expect(parsed.searchParams.get('pageSize')).toBe('25')
    expect(parsed.searchParams.has('status')).toBe(false)
  })

  it('encodes path identifiers', async () => {
    fetchMock.mockResolvedValue(response(200, { applicant: {} }))

    await api.applicant('APP/../evil?x=1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/applicants/APP%2F..%2Fevil%3Fx%3D1')
  })

  it('sends JSON bodies for mutations', async () => {
    fetchMock.mockResolvedValue(response(200, { report_id: 'rep_1', status: 'COMPLETED' }))

    await api.generateReport({ type: 'pdf_role', scope: { role: 'technical_team' } })

    const init = fetchMock.mock.calls[0][1]
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ type: 'pdf_role', scope: { role: 'technical_team' } })
  })

  it('throws a typed ApiError with code and details', async () => {
    fetchMock.mockResolvedValue(
      response(400, {
        error: { code: 'VALIDATION_ERROR', message: 'Bad filter', details: { field: 'minScore' } },
      }),
    )

    await expect(api.applicants({ minScore: -1 })).rejects.toMatchObject({
      name: 'Error',
      message: 'Bad filter',
      status: 400,
      code: 'VALIDATION_ERROR',
      details: { field: 'minScore' },
    })

    try {
      await api.applicants()
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
    }
  })

  it('falls back to a generic error for a non-JSON failure', async () => {
    fetchMock.mockResolvedValue(response(500, 'upstream exploded'))

    await expect(api.overview()).rejects.toThrow('Request failed with status 500')
  })

  it('returns parsed text when a success body is not JSON', async () => {
    fetchMock.mockResolvedValue(response(200, 'plain text'))

    await expect(api.me()).resolves.toBe('plain text')
  })

  it('does not call fetch when a request body is absent and uses GET', async () => {
    fetchMock.mockResolvedValue(response(200, { items: [], total: 0, role: '', minScore: null, maxScore: null }))

    await api.shortlist({ role: 'social_media', limit: 10 })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/shortlist?role=social_media&limit=10')
    expect(init.body).toBeUndefined()
  })
})
