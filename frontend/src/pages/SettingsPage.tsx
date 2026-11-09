import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FileJson,
  Loader2,
  PlayCircle,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  Users,
  Workflow,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { formatDate, humanise } from '../lib/utils'
import { ErrorState, PageLoader } from '../components/States'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { Select } from '../components/ui/select'
import { Textarea } from '../components/ui/textarea'
import type { SettingsPayload } from '../types'

function useSettingsData() {
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  return { data, isLoading, isError, error, refetch }
}

export function SettingsPage() {
  const { can } = useAuth()
  const { data, isLoading, isError, error, refetch } = useSettingsData()
  const [tab, setTab] = useState('organization')

  if (isLoading) return <PageLoader label="Loading configuration…" />
  if (isError || !data) return <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />

  const readOnly = !can('settings')

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-navy-900">Configuration</h2>
        <p className="mt-1 text-xs text-slate-500">
          Every change is versioned and audited. Rubric, eligibility and role weights determine the deterministic score.
        </p>
      </div>

      {readOnly ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Your role has read-only access to configuration.
        </div>
      ) : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="organization">Organization</TabsTrigger>
          <TabsTrigger value="mapping">Field mapping</TabsTrigger>
          <TabsTrigger value="eligibility">Eligibility</TabsTrigger>
          <TabsTrigger value="rubric">Rubric</TabsTrigger>
          <TabsTrigger value="roles">Role weights</TabsTrigger>
          <TabsTrigger value="ai">AI provider</TabsTrigger>
          <TabsTrigger value="processing">Processing</TabsTrigger>
          <TabsTrigger value="administrators">Administrators</TabsTrigger>
        </TabsList>

        <TabsContent value="organization">
          <OrganizationTab data={data} readOnly={readOnly} />
        </TabsContent>
        <TabsContent value="mapping">
          <JsonConfigTab
            configKey="field_mapping"
            title="Google Form field mapping"
            description="Maps form question titles to canonical applicant fields. Add aliases when question wording changes. Unmapped answers are preserved but ignored for scoring."
            value={data.field_mapping}
            meta={data.meta.field_mapping}
            readOnly={readOnly}
          />
        </TabsContent>
        <TabsContent value="eligibility">
          <JsonConfigTab
            configKey="eligibility"
            title="Eligibility rules"
            description="Mandatory failures are flagged for human review — applicants are never auto-rejected. Supported types: required, pattern, min_number, max_number, one_of, contains, boolean_true."
            value={data.eligibility}
            meta={data.meta.eligibility}
            readOnly={readOnly}
          />
        </TabsContent>
        <TabsContent value="rubric">
          <JsonConfigTab
            configKey="rubric"
            title="Evaluation rubric"
            description="Criterion maximums must sum to total_points. The AI proposes a fraction per criterion; Python applies the maximum and computes the final score."
            value={data.rubric}
            meta={data.meta.rubric}
            readOnly={readOnly}
          />
        </TabsContent>
        <TabsContent value="roles">
          <JsonConfigTab
            configKey="roles"
            title="Roles and weight profiles"
            description="Each role must define weights summing to 100 across rubric criterion ids. Role scores are computed independently from the same evidence."
            value={data.roles}
            meta={data.meta.roles}
            readOnly={readOnly}
          />
        </TabsContent>
        <TabsContent value="ai">
          <AiTab data={data} readOnly={readOnly} />
        </TabsContent>
        <TabsContent value="processing">
          <JsonConfigTab
            configKey="processing"
            title="Processing limits"
            description="Document size limits, permitted extensions, OCR toggle and retry policy. Limits must stay compatible with the API Gateway payload cap."
            value={data.processing}
            meta={data.meta.processing}
            readOnly={readOnly}
          />
        </TabsContent>
        <TabsContent value="administrators">
          <AdministratorsTab readOnly={!can('admin')} />
        </TabsContent>
      </Tabs>

      <div className="grid gap-3 md:grid-cols-2">
        <EnvironmentCard data={data} />
        <ConfigMetaCard data={data} />
      </div>
    </div>
  )
}

function OrganizationTab({ data, readOnly }: { data: SettingsPayload; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setValues(
      Object.fromEntries(
        Object.entries(data.organization ?? {}).map(([key, value]) => [key, String(value ?? '')]),
      ),
    )
  }, [data.organization])

  const mutation = useMutation({
    mutationFn: () => api.updateSettings('organization', values),
    onSuccess: () => {
      setMessage('Organization settings saved.')
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (err: Error) => setError(err.message),
  })

  const fields = Object.keys(values).length ? Object.keys(values) : ['name', 'institution', 'cycle']

  return (
    <Card>
      <CardHeader>
        <CardTitle>Organization details</CardTitle>
        <CardDescription>Appears on every report cover, footer and the dashboard header.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {message ? <Banner tone="success" message={message} /> : null}
        {error ? <Banner tone="error" message={error} /> : null}
        <div className="grid gap-3 sm:grid-cols-2">
          {fields.map((field) => (
            <div key={field} className="space-y-1">
              <Label htmlFor={`org-${field}`}>{humanise(field)}</Label>
              <Input
                id={`org-${field}`}
                value={values[field] ?? ''}
                disabled={readOnly}
                onChange={(event) => setValues((prev) => ({ ...prev, [field]: event.target.value }))}
              />
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="accent" size="sm" disabled={readOnly || mutation.isPending} onClick={() => mutation.mutate()}>
            <Save className="h-3.5 w-3.5" /> {mutation.isPending ? 'Saving…' : 'Save organization'}
          </Button>
          <VersionNote meta={data.meta.organization} />
        </div>
      </CardContent>
    </Card>
  )
}

function JsonConfigTab({
  configKey,
  title,
  description,
  value,
  meta,
  readOnly,
}: {
  configKey: string
  title: string
  description: string
  value: Record<string, unknown>
  meta?: SettingsPayload['meta'][string]
  readOnly: boolean
}) {
  const queryClient = useQueryClient()
  const formatted = useMemo(() => JSON.stringify(value, null, 2), [value])
  const [draft, setDraft] = useState(formatted)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [parseError, setParseError] = useState('')

  useEffect(() => {
    setDraft(formatted)
  }, [formatted])

  const mutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.updateSettings(configKey, payload),
    onSuccess: () => {
      setMessage('Configuration saved. New evaluations use this version.')
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (err: Error) => setError(err.message),
  })

  function submit() {
    setMessage('')
    setError('')
    setParseError('')
    let parsed: unknown
    try {
      parsed = JSON.parse(draft)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : 'Invalid JSON')
      return
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setParseError('Configuration must be a JSON object.')
      return
    }
    mutation.mutate(parsed as Record<string, unknown>)
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <FileJson className="h-4 w-4 text-aws-orange" /> {title}
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">{description}</CardDescription>
          </div>
          <VersionNote meta={meta} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {message ? <Banner tone="success" message={message} /> : null}
        {error ? <Banner tone="error" message={error} /> : null}
        {parseError ? <Banner tone="error" message={`JSON error: ${parseError}`} /> : null}
        <Textarea
          className="min-h-[360px] font-mono text-[12px] leading-relaxed"
          spellCheck={false}
          value={draft}
          disabled={readOnly}
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="accent" size="sm" disabled={readOnly || mutation.isPending} onClick={submit}>
            <Save className="h-3.5 w-3.5" /> {mutation.isPending ? 'Validating…' : 'Validate & save'}
          </Button>
          <Button variant="ghost" size="sm" disabled={mutation.isPending} onClick={() => setDraft(formatted)}>
            Reset to current
          </Button>
          <p className="text-[11px] text-slate-400">
            Saved values are validated server-side before they are activated.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

function AiTab({ data, readOnly }: { data: SettingsPayload; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const [provider, setProvider] = useState(data.aiPublic.provider)
  const [model, setModel] = useState(data.aiPublic.model)
  const [baseUrl, setBaseUrl] = useState(data.aiPublic.baseUrl)
  const [enabled, setEnabled] = useState(data.aiPublic.enabled)
  const [temperature, setTemperature] = useState(String(data.aiPublic.temperature))
  const [timeoutSeconds, setTimeoutSeconds] = useState(String(data.aiPublic.timeoutSeconds))
  const [maxRetries, setMaxRetries] = useState(String(data.aiPublic.maxRetries))
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; model?: string; latencyMs?: number } | null>(null)

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateSettings('ai', {
        provider,
        model,
        base_url: baseUrl,
        enabled,
        temperature: Number(temperature),
        timeout_seconds: Number(timeoutSeconds),
        max_retries: Number(maxRetries),
      }),
    onSuccess: () => {
      setMessage('AI settings saved. The API key is managed in AWS Secrets Manager and never exposed here.')
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (err: Error) => setError(err.message),
  })

  const testMutation = useMutation({
    mutationFn: api.testAi,
    onSuccess: (result) => setTestResult(result),
    onError: (err: Error) => setError(err.message),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-aws-orange" /> AI provider configuration
        </CardTitle>
        <CardDescription>
          The model only proposes evidence-backed score fractions. Python validates each value and computes final marks. The API key is read
          from AWS Secrets Manager at runtime.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {message ? <Banner tone="success" message={message} /> : null}
        {error ? <Banner tone="error" message={error} /> : null}
        {testResult ? (
          <Banner tone={testResult.ok ? 'success' : 'error'} message={`${testResult.message}${testResult.latencyMs ? ` (${testResult.latencyMs} ms)` : ''}`} />
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label>Provider</Label>
            <Input value={provider} disabled={readOnly} onChange={(event) => setProvider(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Model</Label>
            <Input value={model} disabled={readOnly} onChange={(event) => setModel(event.target.value)} />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label>Base URL (OpenAI-compatible)</Label>
            <Input value={baseUrl} disabled={readOnly} onChange={(event) => setBaseUrl(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Temperature</Label>
            <Input type="number" step={0.1} min={0} max={2} value={temperature} disabled={readOnly} onChange={(event) => setTemperature(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Timeout (seconds)</Label>
            <Input type="number" min={10} max={300} value={timeoutSeconds} disabled={readOnly} onChange={(event) => setTimeoutSeconds(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Max retries</Label>
            <Input type="number" min={0} max={8} value={maxRetries} disabled={readOnly} onChange={(event) => setMaxRetries(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Provider enabled</Label>
            <Select value={enabled ? 'true' : 'false'} disabled={readOnly} onChange={(event) => setEnabled(event.target.value === 'true')}>
              <option value="true">Enabled</option>
              <option value="false">Disabled (evaluations fail fast)</option>
            </Select>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
              data.aiPublic.apiKeyConfigured ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'
            }`}
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            {data.aiPublic.apiKeyConfigured ? 'API key configured in Secrets Manager' : 'API key not configured'}
          </span>
          {data.environment.localMode ? (
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">Local mock mode</span>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="accent" size="sm" disabled={readOnly || saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            <Save className="h-3.5 w-3.5" /> {saveMutation.isPending ? 'Saving…' : 'Save AI settings'}
          </Button>
          <Button variant="outline" size="sm" disabled={testMutation.isPending} onClick={() => testMutation.mutate()}>
            {testMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}
            Test connection
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function AdministratorsTab({ readOnly }: { readOnly: boolean }) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [group, setGroup] = useState('sbg-reviewers')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ['admins'], queryFn: api.admins })

  const addMutation = useMutation({
    mutationFn: () => api.addAdmin({ email: email.trim(), group }),
    onSuccess: (result) => {
      setMessage(
        result.status === 'SIMULATED'
          ? 'Local mode: group change simulated (Cognito is not configured).'
          : `${result.email} added to ${result.group}.`,
      )
      setError('')
      setEmail('')
      void queryClient.invalidateQueries({ queryKey: ['admins'] })
    },
    onError: (err: Error) => setError(err.message),
  })

  const removeMutation = useMutation({
    mutationFn: (payload: { email: string; group: string }) => api.removeAdmin(payload),
    onSuccess: (result) => {
      setMessage(
        result.status === 'SIMULATED'
          ? 'Local mode: group change simulated (Cognito is not configured).'
          : `${result.email} removed from ${result.group}.`,
      )
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['admins'] })
    },
    onError: (err: Error) => setError(err.message),
  })

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card className="xl:col-span-2">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-4 w-4 text-aws-orange" /> Recruitment administrators
          </CardTitle>
          <CardDescription>Access is granted through Cognito groups. Users must already exist in the user pool.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {message ? <Banner tone="success" message={message} /> : null}
          {error ? <Banner tone="error" message={error} /> : null}
          {isLoading ? <p className="text-xs text-slate-500">Loading administrators…</p> : null}
          {isError ? <ErrorState message="Unable to load administrators" onRetry={() => refetch()} /> : null}
          {data ? (
            <>
              {data.note ? <Banner tone="info" message={data.note} /> : null}
              <div className="overflow-x-auto">
                <table className="data-grid">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Username</th>
                      <th>Status</th>
                      <th>Groups</th>
                      <th className="text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="text-center text-xs text-slate-500">No administrators found.</td>
                      </tr>
                    ) : (
                      data.items.map((user) => (
                        <tr key={user.username}>
                          <td className="text-xs font-medium text-navy-900">{user.email || '—'}</td>
                          <td className="text-xs text-slate-500">{user.username}</td>
                          <td className="text-xs text-slate-500">{humanise(user.status)}</td>
                          <td>
                            <div className="flex flex-wrap gap-1">
                              {user.groups.map((item) => (
                                <span key={item} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                                  {item}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="text-right">
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={readOnly || removeMutation.isPending}
                              onClick={() => removeMutation.mutate({ email: user.email, group: user.groups[user.groups.length - 1] ?? 'sbg-viewers' })}
                            >
                              <Trash2 className="h-3.5 w-3.5" /> Remove
                            </Button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Grant access</CardTitle>
          <CardDescription>
            Administrators can manage configuration. Reviewers can score, review and shortlist. Viewers have read-only access.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label>Email</Label>
            <Input type="email" placeholder="name@sjbit.edu.in" value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Group</Label>
            <Select value={group} onChange={(event) => setGroup(event.target.value)}>
              <option value="sbg-admins">sbg-admins · full access</option>
              <option value="sbg-reviewers">sbg-reviewers · review & shortlist</option>
              <option value="sbg-viewers">sbg-viewers · read only</option>
            </Select>
          </div>
          <Button
            variant="accent"
            size="sm"
            disabled={readOnly || !email.trim() || addMutation.isPending}
            onClick={() => addMutation.mutate()}
          >
            <Plus className="h-3.5 w-3.5" /> {addMutation.isPending ? 'Granting…' : 'Grant access'}
          </Button>
          <p className="text-[11px] leading-relaxed text-slate-500">
            The Cognito administrators group cannot be removed through the dashboard. Changes are recorded in the audit trail.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

function EnvironmentCard({ data }: { data: SettingsPayload }) {
  const env = data.environment
  const entries: [string, string][] = [
    ['Stage', String(env.stage ?? '—')],
    ['Region', String(env.region ?? '—')],
    ['Local mode', env.localMode ? 'Yes' : 'No'],
    ['Textract OCR', env.textractEnabled ? 'Enabled' : 'Disabled'],
    ['Malware scanning', env.malwareScanEnabled ? 'Enabled' : 'Disabled'],
    ['Google Form connected', env.googleFormConnected ? 'Yes' : 'No'],
    ['Processing queue', env.processingQueueConfigured ? 'Configured' : 'Inline / not configured'],
    ['Resume bucket', env.resumeBucketConfigured ? 'Configured' : 'Not configured'],
  ]
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Workflow className="h-4 w-4 text-aws-orange" /> Runtime environment</CardTitle>
        <CardDescription>Read-only deployment information.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
          {entries.map(([label, value]) => (
            <div key={label}>
              <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</dt>
              <dd className="text-xs text-slate-700">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  )
}

function ConfigMetaCard({ data }: { data: SettingsPayload }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Configuration versions</CardTitle>
        <CardDescription>Stored overrides take precedence over packaged defaults.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {Object.entries(data.meta).map(([key, meta]) => (
            <div key={key} className="flex items-center justify-between gap-2 text-xs">
              <span className="font-medium text-slate-700">{humanise(key)}</span>
              <span className="text-slate-500">
                v{meta.version} · {meta.source === 'dynamodb' ? 'custom' : 'default'} · {meta.updated_at ? formatDate(meta.updated_at) : '—'}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function VersionNote({ meta }: { meta?: SettingsPayload['meta'][string] }) {
  if (!meta) return null
  return (
    <p className="text-[11px] text-slate-400">
      Version {meta.version} · {meta.source === 'dynamodb' ? 'custom' : 'packaged default'}
      {meta.updated_at ? ` · ${formatDate(meta.updated_at)}` : ''}
    </p>
  )
}

function Banner({ tone, message }: { tone: 'success' | 'error' | 'info'; message: string }) {
  const palette = {
    success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    error: 'border-red-200 bg-red-50 text-red-700',
    info: 'border-blue-200 bg-blue-50 text-blue-800',
  }[tone]
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'error' ? AlertTriangle : ShieldCheck
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${palette}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  )
}
