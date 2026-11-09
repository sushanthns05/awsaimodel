import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  Download,
  ExternalLink,
  FileText,
  History,
  RotateCcw,
  Save,
  ShieldAlert,
  Sparkles,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { formatDate, formatScore, humanise, initials } from '../lib/utils'
import { EmptyState, ErrorState, PageLoader } from '../components/States'
import { ScoreBadge, RecommendationBadge, StatusBadge, EligibilityBadge, ReviewBadge } from '../components/StatusBadges'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Select } from '../components/ui/select'
import { Textarea } from '../components/ui/textarea'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { Dialog } from '../components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import type { CriterionScore, Evaluation } from '../types'

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function EvidenceList({ items }: { items: string[] }) {
  if (!items.length) return <p className="text-xs italic text-slate-400">No evidence recorded.</p>
  return (
    <ul className="space-y-1.5">
      {items.map((item, index) => (
        <li key={`${index}-${item.slice(0, 12)}`} className="rounded-md border-l-2 border-aws-orange bg-orange-50/50 px-3 py-2 text-xs leading-relaxed text-slate-700">
          “{item}”
        </li>
      ))}
    </ul>
  )
}

function CriterionRow({ criterion, evaluation }: { criterion: CriterionScore; evaluation: Evaluation }) {
  const percentage = criterion.max_score ? (criterion.final_score / criterion.max_score) * 100 : 0
  return (
    <details className="group rounded-lg border border-slate-200 bg-white">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-navy-900">{criterion.name}</p>
          <p className="mt-0.5 text-[11px] text-slate-500">{criterion.reasoning || 'No reasoning provided.'}</p>
        </div>
        <div className="w-32">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-navy-800" style={{ width: `${Math.min(100, percentage)}%` }} />
          </div>
          <p className="mt-1 text-right text-[10px] text-slate-400">{evaluation.rubric_version}</p>
        </div>
        <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-bold tabular-nums text-navy-900">
          {formatScore(criterion.final_score)} / {formatScore(criterion.max_score)}
        </span>
        {!criterion.validated ? <span className="text-[10px] font-bold uppercase text-red-600">Invalid AI value</span> : null}
      </summary>
      <div className="space-y-2 border-t border-slate-100 px-4 py-3">
        <div>
          <p className="field-label mb-1.5">Evidence</p>
          <EvidenceList items={criterion.evidence} />
        </div>
        {criterion.reasoning ? (
          <div>
            <p className="field-label mb-1">Assessment reasoning</p>
            <p className="text-xs leading-relaxed text-slate-600">{criterion.reasoning}</p>
          </div>
        ) : null}
        {criterion.validation_error ? (
          <p className="rounded bg-red-50 px-2 py-1.5 text-[11px] text-red-700">{criterion.validation_error}</p>
        ) : null}
        {criterion.suggested_score !== null ? (
          <p className="text-[11px] text-slate-400">
            AI-proposed fraction: {criterion.suggested_score} · Points computed deterministically by the scoring engine.
          </p>
        ) : null}
      </div>
    </details>
  )
}

export function ApplicantDetailPage() {
  const { applicantId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { can, user } = useAuth()
  const [tab, setTab] = useState('evaluation')
  const [decision, setDecision] = useState('SHORTLISTED')
  const [notes, setNotes] = useState('')
  const [reason, setReason] = useState('')
  const [message, setMessage] = useState('')
  const [actionError, setActionError] = useState('')
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [overrideReason, setOverrideReason] = useState('')
  const [overrideScores, setOverrideScores] = useState<Record<string, number>>({})
  const [openingDocument, setOpeningDocument] = useState('')

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['applicant', applicantId],
    queryFn: () => api.applicant(applicantId),
    enabled: Boolean(applicantId),
  })
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings, staleTime: 300_000 })

  const reviewMutation = useMutation({
    mutationFn: (payload: { decision: string; notes: string; reason: string }) => api.review(applicantId, payload),
    onSuccess: () => {
      setMessage('Review decision saved and audited.')
      setActionError('')
      setReason('')
      void queryClient.invalidateQueries({ queryKey: ['applicant', applicantId] })
      void queryClient.invalidateQueries({ queryKey: ['overview'] })
      void queryClient.invalidateQueries({ queryKey: ['shortlist'] })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const overrideMutation = useMutation({
    mutationFn: () => api.overrideScores(applicantId, { scores: overrideScores, reason: overrideReason }),
    onSuccess: () => {
      setOverrideOpen(false)
      setMessage('Manual score override saved with audit trail.')
      setActionError('')
      void queryClient.invalidateQueries({ queryKey: ['applicant', applicantId] })
      void queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const reprocessMutation = useMutation({
    mutationFn: () => api.reprocess(applicantId),
    onSuccess: () => {
      setMessage('Applicant queued for reprocessing. Existing evaluations are preserved in history.')
      void queryClient.invalidateQueries({ queryKey: ['applicant', applicantId] })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const applicant = data?.applicant
  const evaluation = data?.evaluation ?? null
  const roleNames = settings?.roles.roles ?? []

  const knownAnswers = useMemo(() => {
    if (!applicant) return []
    const excluded = new Set(['raw_answers', 'extra_fields', 'document_errors', 'extraction_warning'])
    return Object.entries(applicant.responses ?? {})
      .filter(([key]) => !excluded.has(key))
      .map(([key, value]) => ({ key, label: humanise(key), value }))
  }, [applicant])

  async function openDocument(documentId: string) {
    setOpeningDocument(documentId)
    try {
      const result = await api.documentUrl(applicantId, documentId)
      window.open(result.url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to open document')
    } finally {
      setOpeningDocument('')
    }
  }

  async function downloadApplicantPdf() {
    setActionError('')
    try {
      const report = await api.generateReport({ type: 'pdf_applicant', scope: { applicant_id: applicantId } })
      if (report.downloadUrl) window.open(report.downloadUrl, '_blank', 'noopener,noreferrer')
      else setMessage('Applicant PDF is being generated. Check Reports for the download.')
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to generate applicant report')
    }
  }

  function openOverride() {
    if (!evaluation) return
    setOverrideScores(Object.fromEntries(evaluation.criteria.map((criterion) => [criterion.criterion_id, criterion.final_score])))
    setOverrideReason('')
    setActionError('')
    setOverrideOpen(true)
  }

  if (isLoading) return <PageLoader label="Loading applicant record…" />
  if (isError || !data || !applicant) return <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />

  const requiresReason = applicant.eligibility_status === 'FAIL' || ['NEEDS_REVIEW', 'ELIGIBILITY_REVIEW'].includes(applicant.recommendation)
  const reviewLocked = !can('review')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => void downloadApplicantPdf()}>
            <Download className="h-3.5 w-3.5" /> Applicant PDF
          </Button>
          {can('reprocess') ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (window.confirm('Reprocess this applicant with the current rubric? Existing evaluations remain in history.')) {
                  reprocessMutation.mutate()
                }
              }}
              disabled={reprocessMutation.isPending}
            >
              <RotateCcw className="h-3.5 w-3.5" /> {reprocessMutation.isPending ? 'Queueing…' : 'Reprocess'}
            </Button>
          ) : null}
        </div>
      </div>

      <Card>
        <CardContent className="p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-navy-900 text-base font-bold text-white">
                {initials(applicant.full_name)}
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-2xl font-bold tracking-tight text-navy-900">{applicant.full_name || 'Unnamed applicant'}</h2>
                  <StatusBadge value={applicant.processing_status} />
                  <ReviewBadge value={applicant.review_status} />
                  {applicant.urgent_review ? <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-bold uppercase text-orange-800">Needs attention</span> : null}
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {applicant.applicant_id} · {applicant.email || 'no email'} · {applicant.usn || 'no USN'} · {applicant.department || 'no department'} · Year {applicant.year_of_study || '—'}
                </p>
                <p className="mt-1 text-[11px] text-slate-400">
                  Submitted {formatDate(applicant.submitted_at)} · Source response {applicant.source_response_id.slice(0, 12)}… · Rubric {applicant.rubric_version || '—'}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {applicant.roles.map((role) => (
                    <span key={role} className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                      {roleNames.find((item) => item.id === role)?.name ?? humanise(role)}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="field-label">Final score</p>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-2xl font-bold tabular-nums text-navy-900">{formatScore(applicant.total_score)}</span>
                  <span className="text-xs text-slate-400">/ 100</span>
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="field-label">Recommendation</p>
                <div className="mt-1"><RecommendationBadge value={applicant.recommendation} /></div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="field-label">Eligibility</p>
                <div className="mt-1"><EligibilityBadge value={applicant.eligibility_status} /></div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="field-label">Documents</p>
                <div className="mt-1 flex items-center gap-2">
                  <FileText className="h-4 w-4 text-slate-500" />
                  <span className="text-lg font-bold tabular-nums text-navy-900">{data.documents.length}</span>
                  <span className="text-[11px] text-slate-400">{applicant.extracted_text_chars.toLocaleString('en-IN')} chars</span>
                </div>
              </div>
            </div>
          </div>

          {applicant.processing_error ? (
            <div className="mt-4 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>Processing error: {applicant.processing_error}</span>
            </div>
          ) : null}
          {message ? (
            <div className="mt-4 flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
              <CheckCircle2 className="h-4 w-4" /> {message}
            </div>
          ) : null}
          {actionError ? (
            <div className="mt-4 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {actionError}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="evaluation">AI evaluation</TabsTrigger>
          <TabsTrigger value="application">Application</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="review">Human review</TabsTrigger>
          <TabsTrigger value="history">History & audit</TabsTrigger>
        </TabsList>

        <TabsContent value="evaluation">
          {!evaluation ? (
            <EmptyState
              title="No evaluation available"
              description={
                applicant.processing_status === 'FAILED'
                  ? 'Processing failed. Use Reprocess to retry this application.'
                  : 'This application has not completed AI evaluation yet.'
              }
              icon={<ClipboardList className="h-5 w-5" />}
            />
          ) : (
            <div className="space-y-4">
              {!evaluation.score_complete || evaluation.validation_errors.length ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
                  <p className="font-semibold">This evaluation requires human verification.</p>
                  <ul className="mt-1 list-disc pl-4">
                    {evaluation.validation_errors.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-3">
                <Card className="xl:col-span-2">
                  <CardHeader>
                    <CardTitle>AI summary</CardTitle>
                    <CardDescription>
                      Model: {String(evaluation.model_metadata?.model ?? 'unknown')} · Confidence {evaluation.confidence} ·{' '}
                      {String(evaluation.model_metadata?.prompt_tokens ?? 0)} / {String(evaluation.model_metadata?.completion_tokens ?? 0)} tokens
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <p className="text-sm leading-relaxed text-slate-700">{evaluation.summary || 'No summary generated.'}</p>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <p className="field-label mb-1.5">Strengths</p>
                        {evaluation.strengths.length ? (
                          <ul className="space-y-1 text-xs text-slate-600">
                            {evaluation.strengths.map((item) => <li key={item} className="flex gap-1.5"><CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" />{item}</li>)}
                          </ul>
                        ) : <p className="text-xs italic text-slate-400">None identified.</p>}
                      </div>
                      <div>
                        <p className="field-label mb-1.5">Weaknesses / concerns</p>
                        {evaluation.weaknesses.length ? (
                          <ul className="space-y-1 text-xs text-slate-600">
                            {evaluation.weaknesses.map((item) => <li key={item} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-600" />{item}</li>)}
                          </ul>
                        ) : <p className="text-xs italic text-slate-400">None identified.</p>}
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Role fit</CardTitle>
                    <CardDescription>Scores use each role&apos;s weighting profile.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {evaluation.role_evaluations.map((item) => (
                      <div key={item.role_id} className="rounded-lg border border-slate-200 p-3">
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-semibold text-navy-900">{roleNames.find((role) => role.id === item.role_id)?.name ?? humanise(item.role_id)}</p>
                          <ScoreBadge score={item.score} />
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500">Fit: {humanise(item.fit)}</p>
                        {item.rationale ? <p className="mt-1 text-xs text-slate-600">{item.rationale}</p> : null}
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                <Card className="xl:col-span-2">
                  <CardHeader>
                    <CardTitle>Criterion-wise evaluation</CardTitle>
                    <CardDescription>Expand a criterion to review the evidence quotes and reasoning.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {evaluation.criteria.map((criterion) => (
                      <CriterionRow key={criterion.criterion_id} criterion={criterion} evaluation={evaluation} />
                    ))}
                    <div className="flex items-center justify-between rounded-lg bg-navy-900 px-4 py-3 text-white">
                      <span className="text-sm font-semibold">Deterministic total</span>
                      <span className="text-lg font-bold tabular-nums">{formatScore(evaluation.total_score)} / {formatScore(evaluation.max_score)}</span>
                    </div>
                    {can('review') ? (
                      <Button variant="outline" size="sm" onClick={openOverride}>
                        <Save className="h-3.5 w-3.5" /> Manually correct scores
                      </Button>
                    ) : null}
                  </CardContent>
                </Card>

                <div className="space-y-4">
                  <Card>
                    <CardHeader>
                      <CardTitle>Eligibility checks</CardTitle>
                      <CardDescription>Mandatory failures are flagged for human verification, never auto-rejected.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2">
                      {evaluation.eligibility.map((rule) => (
                        <div key={rule.rule_id} className="rounded-md border border-slate-100 bg-slate-50/60 px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-xs font-semibold text-navy-900">{rule.label}</p>
                            <span className={`text-[10px] font-bold uppercase ${rule.status === 'PASS' ? 'text-emerald-700' : rule.status === 'FAIL' ? 'text-red-700' : 'text-amber-700'}`}>
                              {rule.status}
                            </span>
                          </div>
                          {rule.detail ? <p className="mt-0.5 text-[11px] text-slate-500">{rule.detail}</p> : null}
                          {rule.observed ? <p className="mt-0.5 text-[10px] text-slate-400">Observed: {rule.observed}</p> : null}
                          {!rule.mandatory ? <p className="text-[10px] text-slate-400">Advisory check</p> : null}
                        </div>
                      ))}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle>Missing & uncertain</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3 text-xs text-slate-600">
                      <div>
                        <p className="field-label mb-1">Missing information</p>
                        {evaluation.missing_information.length ? <ul className="list-disc pl-4">{evaluation.missing_information.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="italic text-slate-400">None.</p>}
                      </div>
                      <div>
                        <p className="field-label mb-1">Inconsistencies</p>
                        {evaluation.inconsistencies.length ? <ul className="list-disc pl-4">{evaluation.inconsistencies.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="italic text-slate-400">None flagged.</p>}
                      </div>
                      <div>
                        <p className="field-label mb-1">Uncertain findings</p>
                        {evaluation.uncertain_findings.length ? <ul className="list-disc pl-4">{evaluation.uncertain_findings.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="italic text-slate-400">None.</p>}
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-aws-orange" /> Recommended interview questions</CardTitle>
                    <CardDescription>Role-specific probes generated from this application.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {evaluation.interview_questions.length ? evaluation.interview_questions.map((question, index) => (
                      <div key={`${question.question}-${index}`} className="rounded-lg border border-slate-200 px-3 py-2">
                        <p className="text-xs font-semibold text-navy-900">{index + 1}. {question.question}</p>
                        <p className="mt-0.5 text-[11px] text-slate-500">
                          {roleNames.find((role) => role.id === question.role)?.name ?? humanise(question.role)}
                          {question.why ? ` · ${question.why}` : ''}
                        </p>
                      </div>
                    )) : <p className="text-xs italic text-slate-400">No questions generated.</p>}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Extracted profile</CardTitle>
                    <CardDescription>Skills, projects and experience identified from the application and resume.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3 text-xs text-slate-600">
                    <div>
                      <p className="field-label mb-1">Technical skills</p>
                      <div className="flex flex-wrap gap-1">
                        {evaluation.technical_skills.length ? evaluation.technical_skills.map((skill) => <span key={skill} className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-800">{skill}</span>) : <span className="italic text-slate-400">None extracted.</span>}
                      </div>
                    </div>
                    <div>
                      <p className="field-label mb-1">Non-technical skills</p>
                      <div className="flex flex-wrap gap-1">
                        {evaluation.nontechnical_skills.length ? evaluation.nontechnical_skills.map((skill) => <span key={skill} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">{skill}</span>) : <span className="italic text-slate-400">None extracted.</span>}
                      </div>
                    </div>
                    <div>
                      <p className="field-label mb-1">Certifications</p>
                      {evaluation.certifications.length ? evaluation.certifications.map((item) => <p key={item}>• {item}</p>) : <p className="italic text-slate-400">None.</p>}
                    </div>
                    <div>
                      <p className="field-label mb-1">Document coverage</p>
                      <p>{String(evaluation.document_coverage?.extracted_documents ?? 0)} document(s) extracted · {String(evaluation.document_coverage?.resume_characters ?? 0)} resume characters</p>
                      {evaluation.document_coverage?.used_application_answers_only ? <p className="text-amber-700">Evaluation used application answers only.</p> : null}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="application">
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>Application answers</CardTitle>
                <CardDescription>Original responses captured from Google Forms, preserved verbatim.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {knownAnswers.map((item) => (
                  <div key={item.key} className="rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2">
                    <p className="field-label">{item.label}</p>
                    <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-700">{displayValue(item.value)}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Submission metadata</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-xs text-slate-600">
                  <p><span className="font-semibold text-slate-500">Applicant ID:</span> {applicant.applicant_id}</p>
                  <p><span className="font-semibold text-slate-500">Source response:</span> {applicant.source_response_id}</p>
                  <p><span className="font-semibold text-slate-500">Form:</span> {applicant.form_title || '—'}</p>
                  <p><span className="font-semibold text-slate-500">Submitted:</span> {formatDate(applicant.submitted_at)}</p>
                  <p><span className="font-semibold text-slate-500">Complete:</span> {applicant.application_complete ? 'Yes' : 'No'}</p>
                  {applicant.missing_required_fields.length ? (
                    <div>
                      <p className="font-semibold text-slate-500">Missing fields:</p>
                      <ul className="list-disc pl-4">{applicant.missing_required_fields.map((item) => <li key={item}>{item}</li>)}</ul>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Unmapped questions</CardTitle>
                  <CardDescription>Answers that did not match the field mapping are preserved here.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs text-slate-600">
                  {Object.entries((applicant.responses?.extra_fields as Record<string, unknown>) ?? {}).length ? (
                    Object.entries((applicant.responses?.extra_fields as Record<string, unknown>) ?? {}).map(([key, value]) => (
                      <div key={key}>
                        <p className="font-semibold text-slate-500">{key}</p>
                        <p className="whitespace-pre-wrap break-words">{displayValue(value)}</p>
                      </div>
                    ))
                  ) : <p className="italic text-slate-400">All questions matched the mapping.</p>}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="documents">
          <Card>
            <CardHeader>
              <CardTitle>Uploaded documents</CardTitle>
              <CardDescription>Files are private. Opening a document issues a short-lived signed URL and is audited.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.documents.length === 0 ? (
                <EmptyState title="No documents attached" description="This application did not include a readable resume." icon={<FileText className="h-5 w-5" />} />
              ) : (
                data.documents.map((document) => (
                  <div key={document.document_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="rounded-lg bg-slate-100 p-2"><FileText className="h-4 w-4 text-slate-600" /></div>
                      <div>
                        <p className="text-sm font-semibold text-navy-900">{document.filename}</p>
                        <p className="text-[11px] text-slate-500">
                          {(document.size_bytes / 1024).toFixed(1)} KB · {document.extraction_status} · {document.text_chars.toLocaleString('en-IN')} chars
                          {document.textract_used ? ' · OCR' : ''}
                          {document.page_count ? ` · ${document.page_count} pages` : ''}
                        </p>
                        {document.extraction_error ? <p className="text-[11px] text-amber-700">{document.extraction_error}</p> : null}
                      </div>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => void openDocument(document.document_id)} disabled={openingDocument === document.document_id}>
                      <ExternalLink className="h-3.5 w-3.5" /> {openingDocument === document.document_id ? 'Opening…' : 'Open'}
                    </Button>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="review">
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Human decision</CardTitle>
                <CardDescription>
                  Record the final recruitment decision. Eligibility failures and incomplete applications require a written reason before shortlisting.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1">
                  <Label>Decision</Label>
                  <Select value={decision} onChange={(event) => setDecision(event.target.value)} disabled={reviewLocked}>
                    <option value="SHORTLISTED">Shortlist for interview</option>
                    <option value="MANUAL_REVIEW">Flag for manual review</option>
                    <option value="REJECTED">Not shortlisted</option>
                    <option value="PENDING">Reset to pending</option>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>Reviewer notes</Label>
                  <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Interview focus, panel notes, follow-up questions…" disabled={reviewLocked} maxLength={4000} />
                </div>
                <div className="space-y-1">
                  <Label>Reason {requiresReason ? <span className="text-red-600">(required for this applicant)</span> : '(optional)'}</Label>
                  <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain any override of the AI recommendation" disabled={reviewLocked} maxLength={1000} />
                </div>
                <Button
                  variant="accent"
                  onClick={() => reviewMutation.mutate({ decision, notes, reason })}
                  disabled={reviewLocked || reviewMutation.isPending}
                >
                  <Save className="h-4 w-4" /> {reviewMutation.isPending ? 'Saving…' : 'Save decision'}
                </Button>
                {reviewLocked ? <p className="text-[11px] text-amber-700">Your role has read-only access.</p> : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Current decision record</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-slate-600">
                <p><span className="font-semibold text-slate-500">Review status:</span> {humanise(applicant.review_status)}</p>
                <p><span className="font-semibold text-slate-500">Decision:</span> {humanise(applicant.review_decision)}</p>
                <p><span className="font-semibold text-slate-500">Reviewed by:</span> {applicant.reviewed_by || '—'}</p>
                <p><span className="font-semibold text-slate-500">Reviewed at:</span> {formatDate(applicant.reviewed_at)}</p>
                <div>
                  <p className="font-semibold text-slate-500">Notes:</p>
                  <p className="mt-1 whitespace-pre-wrap rounded-md bg-slate-50 p-3">{applicant.review_notes || 'No notes recorded.'}</p>
                </div>
                {applicant.eligibility_failures.length ? (
                  <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-800">
                    <p className="font-semibold">Eligibility flags</p>
                    <ul className="mt-1 list-disc pl-4">{applicant.eligibility_failures.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="history">
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Evaluation history</CardTitle>
                <CardDescription>Every AI evaluation is retained; reprocessing adds a new version.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.evaluationHistory.map((item) => (
                  <div key={item.evaluationId} className="rounded-lg border border-slate-200 px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-navy-900">{formatDate(item.createdAt)}</p>
                      <div className="flex items-center gap-2">
                        <ScoreBadge score={item.totalScore} />
                        <RecommendationBadge value={item.recommendation} />
                      </div>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {item.evaluationId} · rubric {item.rubricVersion} · model {item.model || 'unknown'} · {item.scoreComplete ? 'validated' : 'incomplete'}
                    </p>
                    {item.validationErrors.length ? <p className="text-[11px] text-amber-700">{item.validationErrors.join('; ')}</p> : null}
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><History className="h-4 w-4" /> Audit trail</CardTitle>
                <CardDescription>Immutable record of system and human actions.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.audit.length === 0 ? <EmptyState title="No audit entries" /> : data.audit.map((entry) => (
                  <div key={entry.audit_id} className="border-l-2 border-slate-200 pl-3">
                    <p className="text-xs font-semibold text-navy-900">{humanise(entry.action)}</p>
                    <p className="text-[11px] text-slate-500">{formatDate(entry.timestamp)} · {entry.reviewer}</p>
                    {entry.reason ? <p className="mt-0.5 text-[11px] text-slate-600">Reason: {entry.reason}</p> : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog
        open={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        title="Manually correct criterion scores"
        description="Changes are audited and recompute the total deterministically. The AI suggestion remains in history."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOverrideOpen(false)}>Cancel</Button>
            <Button
              variant="accent"
              onClick={() => overrideMutation.mutate()}
              disabled={overrideMutation.isPending || overrideReason.trim().length < 5}
            >
              <Save className="h-4 w-4" /> {overrideMutation.isPending ? 'Saving…' : 'Save override'}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {evaluation?.criteria.map((criterion) => (
            <div key={criterion.criterion_id} className="flex items-center justify-between gap-3">
              <Label className="flex-1">{criterion.name} <span className="text-slate-400">(max {criterion.max_score})</span></Label>
              <Input
                type="number"
                min={0}
                max={criterion.max_score}
                step={0.5}
                className="w-24 text-right"
                value={overrideScores[criterion.criterion_id] ?? 0}
                onChange={(event) => setOverrideScores((prev) => ({ ...prev, [criterion.criterion_id]: Number(event.target.value) }))}
              />
            </div>
          ))}
          <div className="space-y-1">
            <Label>Reason for override <span className="text-red-600">*</span></Label>
            <Textarea value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="Explain the correction and cite the evidence reviewed." />
          </div>
          <p className="text-[11px] text-slate-500">Reviewer: {user?.email || '—'}</p>
        </div>
      </Dialog>
    </div>
  )
}
