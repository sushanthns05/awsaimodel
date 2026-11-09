import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SettingsPayload } from '../types'

const { mockApi, mockCan } = vi.hoisted(() => ({
  mockApi: {
    settings: vi.fn(),
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

const { SettingsPage } = await import('./SettingsPage')

const SETTINGS: SettingsPayload = {
  rubric: {
    version: '1.0.0',
    total_points: 100,
    criteria: [{ id: 'relevant_skills', name: 'Relevant skills', max_score: 100 }],
  },
  eligibility: { version: '1.0.0', rules: [] },
  roles: {
    version: '1.0.0',
    default_role: 'technical_team',
    roles: [
      {
        id: 'technical_team',
        name: 'Technical Team',
        description: '',
        evaluation_focus: [],
        interview_topics: [],
        weights: {},
      },
    ],
  },
  field_mapping: { version: '1.0.0', fields: [] },
  processing: { max_documents: 8, textract_enabled: true },
  organization: { name: 'AWS Student Builder Group', institution: 'SJBIT', cycle: '2026-27' },
  aiPublic: {
    provider: 'deepseek',
    model: 'deepseek-flash',
    baseUrl: 'https://api.deepseek.com/v1',
    enabled: true,
    timeoutSeconds: 90,
    maxRetries: 4,
    temperature: 0.1,
    apiKeyConfigured: false,
  },
  environment: {
    stage: 'test',
    region: 'ap-south-1',
    localMode: true,
    textractEnabled: false,
    malwareScanEnabled: false,
    googleFormConnected: false,
    processingQueueConfigured: false,
    resumeBucketConfigured: true,
  },
  meta: {
    rubric: { key: 'rubric', version: 0, updated_at: null, updated_by: 'system', source: 'packaged_default' },
  },
  serverTime: '2026-01-01T00:00:00Z',
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  )
}

async function openRubricTab() {
  const user = userEvent.setup()
  renderPage()
  await screen.findByText('Organization details')
  await user.click(screen.getByRole('tab', { name: 'Rubric' }))
  return { user, textarea: screen.getByRole('textbox') as HTMLTextAreaElement }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockCan.mockReturnValue(true)
  mockApi.settings.mockResolvedValue(SETTINGS)
  mockApi.updateSettings.mockResolvedValue({ key: 'rubric', version: 1, value: {} })
})

describe('SettingsPage', () => {
  it('renders the configuration without exposing AI secrets', async () => {
    renderPage()

    expect(await screen.findByText('Organization details')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('AWS Student Builder Group')).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'AI provider' }))

    expect(screen.getByText('API key not configured')).toBeInTheDocument()
    expect(screen.queryByDisplayValue(/sk-/)).not.toBeInTheDocument()
  })

  it('reports malformed JSON and does not call the API', async () => {
    const { user, textarea } = await openRubricTab()

    fireEvent.change(textarea, { target: { value: '{ "criteria": [ }' } })
    await user.click(screen.getByRole('button', { name: /Validate & save/i }))

    expect(await screen.findByText(/JSON error:/)).toBeInTheDocument()
    expect(mockApi.updateSettings).not.toHaveBeenCalled()
  })

  it('rejects JSON values that are not objects', async () => {
    const { user, textarea } = await openRubricTab()

    fireEvent.change(textarea, { target: { value: '[]' } })
    await user.click(screen.getByRole('button', { name: /Validate & save/i }))

    expect(await screen.findByText('JSON error: Configuration must be a JSON object.')).toBeInTheDocument()
    expect(mockApi.updateSettings).not.toHaveBeenCalled()
  })

  it('submits a validated rubric object', async () => {
    const { user, textarea } = await openRubricTab()

    fireEvent.change(textarea, {
      target: { value: JSON.stringify({ version: '2.0.0', total_points: 100, criteria: [] }, null, 2) },
    })
    await user.click(screen.getByRole('button', { name: /Validate & save/i }))

    await waitFor(() =>
      expect(mockApi.updateSettings).toHaveBeenCalledWith('rubric', {
        version: '2.0.0',
        total_points: 100,
        criteria: [],
      }),
    )
    expect(await screen.findByText('Configuration saved. New evaluations use this version.')).toBeInTheDocument()
  })

  it('shows a server-side validation message', async () => {
    mockApi.updateSettings.mockRejectedValue(new Error('Criterion maximums must sum to total_points'))
    const { user, textarea } = await openRubricTab()

    fireEvent.change(textarea, { target: { value: JSON.stringify({ version: '2.0.0' }) } })
    await user.click(screen.getByRole('button', { name: /Validate & save/i }))

    expect(await screen.findByText('Criterion maximums must sum to total_points')).toBeInTheDocument()
  })

  it('makes the configuration read-only without the settings permission', async () => {
    mockCan.mockReturnValue(false)
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('Organization details')
    expect(screen.getByText('Your role has read-only access to configuration.')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Rubric' }))
    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(screen.getByRole('button', { name: /Validate & save/i })).toBeDisabled()
  })
})
