import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SettingsPayload, ShortlistItem } from '../types'

const { mockApi, mockCan } = vi.hoisted(() => ({
  mockApi: {
    settings: vi.fn(),
    shortlist: vi.fn(),
    bulkDecision: vi.fn(),
    generateReport: vi.fn(),
    reportDownload: vi.fn(),
    applicant: vi.fn(),
    updateSettings: vi.fn(),
    testAi: vi.fn(),
    admins: vi.fn(),
    addAdmin: vi.fn(),
    removeAdmin: vi.fn(),
  },
  mockCan: vi.fn(() => true),
}))

vi.mock('../lib/api', () => ({ api: mockApi }))
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ can: mockCan }) }))

const { ShortlistPage } = await import('./ShortlistPage')

const SETTINGS = {
  roles: {
    version: '1.0.0',
    default_role: 'technical_team',
    roles: [{ id: 'technical_team', name: 'Technical Team', description: '', evaluation_focus: [], interview_topics: [], weights: {} }],
  },
} as unknown as SettingsPayload

function item(overrides: Partial<ShortlistItem> = {}): ShortlistItem {
  return {
    applicantId: 'APP-1',
    fullName: 'Asha Rao',
    email: 'asha@example.com',
    usn: '1AB23CS001',
    department: 'Computer Science',
    yearOfStudy: '3',
    roles: ['technical_team'],
    roleScore: 88,
    totalScore: 85,
    recommendation: 'STRONG_INTERVIEW',
    eligibilityStatus: 'PASS',
    eligibilityFailures: [],
    reviewStatus: 'PENDING',
    reviewDecision: '',
    reviewedBy: '',
    strongestEvidence: ['Built a serverless pipeline on AWS'],
    concerns: [],
    urgentReview: false,
    documents: 1,
    rank: 1,
    ...overrides,
  }
}

function shortlist(items: ShortlistItem[]) {
  return { items, total: items.length, role: '', minScore: null, maxScore: null }
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/shortlist']}>
        <ShortlistPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockCan.mockReturnValue(true)
  mockApi.settings.mockResolvedValue(SETTINGS)
  mockApi.shortlist.mockResolvedValue(
    shortlist([
      item(),
      item({
        applicantId: 'APP-2',
        fullName: 'Ravi Kumar',
        email: 'ravi@example.com',
        usn: '1AB23CS002',
        roleScore: 64,
        totalScore: 62,
        recommendation: 'MANUAL_REVIEW',
        eligibilityStatus: 'FAIL',
        urgentReview: true,
        rank: 2,
      }),
    ]),
  )
  mockApi.bulkDecision.mockResolvedValue({ updated: ['APP-1'], skipped: [], decision: 'SHORTLISTED' })
})

describe('ShortlistPage', () => {
  it('renders the ranked applicants returned by the API', async () => {
    renderPage()

    expect(await screen.findByText('Asha Rao')).toBeInTheDocument()
    expect(screen.getByText('Ravi Kumar')).toBeInTheDocument()
    expect(screen.getByText('Ranked by deterministic score')).toBeInTheDocument()
    expect(mockApi.shortlist).toHaveBeenCalledWith({ role: '', minScore: undefined, maxScore: undefined, limit: 300 })
  })

  it('enables bulk actions only after a selection is made', async () => {
    const user = userEvent.setup()
    renderPage()

    const approve = await screen.findByRole('button', { name: /Approve selected/i })
    expect(approve).toBeDisabled()

    await user.click(await screen.findByLabelText('Select Asha Rao'))
    expect(approve).toBeEnabled()

    await user.click(screen.getByLabelText('Select Asha Rao'))
    expect(approve).toBeDisabled()
  })

  it('requires a written reason and submits the selected applicants', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('Asha Rao')
    await user.click(screen.getByLabelText('Select Asha Rao'))
    await user.click(screen.getByRole('button', { name: /Approve selected/i }))

    const dialog = await screen.findByRole('dialog', { name: 'Approve selected applicants' })
    expect(dialog).toBeInTheDocument()
    expect(screen.getByText('1 applicant will be updated. A written reason is required when overriding flags.')).toBeInTheDocument()

    const reason = 'Panel verified the project evidence during a follow-up call.'
    const reasonBox = screen.getByPlaceholderText(/Explain why these applicants should be approved or rejected/i)
    await user.type(reasonBox, reason)
    await user.click(screen.getByRole('button', { name: 'Approve shortlist' }))

    await waitFor(() =>
      expect(mockApi.bulkDecision).toHaveBeenCalledWith({
        applicantIds: ['APP-1'],
        decision: 'SHORTLISTED',
        notes: '',
        reason,
      }),
    )
    expect(await screen.findByText('1 applicant updated.')).toBeInTheDocument()
  })

  it('warns when a flagged applicant is included in the decision', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('Ravi Kumar')
    await user.click(screen.getByLabelText('Select Ravi Kumar'))
    await user.click(screen.getByRole('button', { name: /Approve selected/i }))

    expect(
      await screen.findByText('1 selected applicant is ineligible or incomplete. A written reason is required.'),
    ).toBeInTheDocument()
  })

  it('select all toggles every visible applicant', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('Asha Rao')
    const selectAll = screen.getByLabelText('Select all applicants')
    await user.click(selectAll)

    expect(screen.getByLabelText('Select Asha Rao')).toBeChecked()
    expect(screen.getByLabelText('Select Ravi Kumar')).toBeChecked()
    expect(selectAll).toBeChecked()

    await user.click(selectAll)
    expect(screen.getByLabelText('Select Asha Rao')).not.toBeChecked()
  })

  it('hides decision controls for users without the shortlist permission', async () => {
    mockCan.mockReturnValue(false)
    renderPage()

    await screen.findByText('Asha Rao')
    expect(screen.queryByRole('button', { name: /Approve selected/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reject selected/i })).not.toBeInTheDocument()
  })
})
