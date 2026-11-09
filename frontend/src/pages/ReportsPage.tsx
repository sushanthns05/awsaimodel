import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  FileText,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Users,
  Clock,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { formatDate, humanise } from '../lib/utils'
import { EmptyState, ErrorState, PageLoader } from '../components/States'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Select } from '../components/ui/select'
import { Label } from '../components/ui/label'
import { Input } from '../components/ui/input'
import type { ReportRecord } from '../types'

const REPORT_TYPES = [
  {
    type: 'excel',
    title: 'Master Excel workbook',
    description:
      'Twelve structured sheets: summary, all applicants, eligibility, per-role rankings, manual review queue, interview shortlist, evaluation template and audit history.',
    icon: FileSpreadsheet,
    accent: 'bg-emerald-50 text-emerald-700',
  },
  {
    type: 'pdf_consolidated',
    title: 'Consolidated evaluation PDF',
    description:
      'Full evidence-backed evaluation for every applicant, including criterion scores, eligibility checks, strengths, concerns and suggested interview questions.',
    icon: FileText,
    accent: 'bg-blue-50 text-blue-700',
  },
  {
    type: 'pdf_executive',
    title: 'Executive summary PDF',
    description:
      'One-page leadership view: pipeline statistics, score distribution, role overview and the human-approved interview shortlist.',
    icon: Users,
    accent: 'bg-navy-50 text-navy-800',
  },
  {
    type: 'pdf_manual_review',
    title: 'Manual review PDF',
    description:
      'Every applicant needing human attention with the specific eligibility failures, validation warnings and uncertainty that triggered the flag.',
    icon: ShieldAlert,
    accent: 'bg-amber-50 text-amber-700',
  },
] as const

export function ReportsPage() {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const [role, setRole] = useState('')
  const [applicantId, setApplicantId] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings, staleTime: 300_000 })
  const roles = settings?.roles.roles ?? []

  const { data, isLoading, isError, error: queryError, refetch, isFetching } = useQuery({
    queryKey: ['reports'],
    queryFn: api.reports,
    refetchInterval: (query) => {
      const items = (query.state.data as { items: ReportRecord[] } | undefined)?.items ?? []
      return items.some((item) => item.status === 'PENDING' || item.status === 'RUNNING') ? 4000 : false
    },
  })

  const generateMutation = useMutation({
    mutationFn: (payload: { type: string; scope?: { role?: string; applicant_id?: string } }) =>
      api.generateReport(payload),
    onSuccess: (record) => {
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      if (record.downloadUrl) {
        window.open(record.downloadUrl, '_blank', 'noopener,noreferrer')
        setMessage(`${humanise(record.kind)} generated and downloaded.`)
      } else {
        setMessage(`${humanise(record.kind)} is being generated. It will appear below when ready.`)
      }
      setError('')
    },
    onError: (err: Error) => setError(err.message),
  })

  async function download(record: ReportRecord) {
    try {
      const result = await api.reportDownload(record.report_id)
      window.open(result.url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to download report')
    }
  }

  function generate(type: string, scope?: { role?: string; applicant_id?: string }) {
    setMessage('')
    setError('')
    generateMutation.mutate({ type, scope })
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-navy-900">Reports & exports</h2>
          <p className="mt-1 text-xs text-slate-500">
            Generate auditable Excel and PDF reports. Files are written to a private bucket and delivered through short-lived signed URLs.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {message ? (
        <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          <CheckCircle2 className="h-4 w-4" /> {message}
        </div>
      ) : null}
      {error ? (
        <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        {REPORT_TYPES.map((report) => (
          <Card key={report.type}>
            <CardContent className="flex h-full flex-col gap-3 p-5">
              <div className="flex items-start gap-3">
                <div className={`rounded-lg p-2.5 ${report.accent}`}>
                  <report.icon className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-navy-900">{report.title}</h3>
                  <p className="mt-1 text-xs leading-relaxed text-slate-500">{report.description}</p>
                </div>
              </div>
              <div className="mt-auto">
                <Button
                  variant="default"
                  size="sm"
                  disabled={!can('reports') || generateMutation.isPending}
                  onClick={() => generate(report.type)}
                >
                  {generateMutation.isPending && generateMutation.variables?.type === report.type ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )}
                  Generate
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Role-wise shortlist PDF</CardTitle>
            <CardDescription>Ranked applicants for a single role with evidence and scores.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label>Role</Label>
              <Select value={role} onChange={(event) => setRole(event.target.value)}>
                <option value="">Select a role…</option>
                {roles.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </Select>
            </div>
            <Button variant="outline" size="sm" disabled={!role || !can('reports')} onClick={() => generate('pdf_role', { role })}>
              <FileText className="h-3.5 w-3.5" /> Generate role PDF
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Individual applicant PDF</CardTitle>
            <CardDescription>Complete evaluation report for one applicant, suitable for panel packs.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label>Applicant ID</Label>
              <Input placeholder="APP-…" value={applicantId} onChange={(event) => setApplicantId(event.target.value.trim())} />
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={!applicantId || !can('reports')}
              onClick={() => generate('pdf_applicant', { applicant_id: applicantId })}
            >
              <FileText className="h-3.5 w-3.5" /> Generate applicant PDF
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Generated reports</CardTitle>
          <CardDescription>Reports are retained per the configured retention policy. Downloads are audited.</CardDescription>
        </CardHeader>
        {isLoading ? <PageLoader label="Loading reports…" /> : null}
        {isError ? <div className="p-5"><ErrorState message={(queryError as Error)?.message} onRetry={() => refetch()} /></div> : null}
        {!isLoading && !isError ? (
          data && data.items.length ? (
            <div className="overflow-x-auto">
              <table className="data-grid">
                <thead>
                  <tr>
                    <th>Report</th>
                    <th>Type</th>
                    <th>Generated</th>
                    <th>By</th>
                    <th>Status</th>
                    <th className="text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((record) => (
                    <tr key={record.report_id}>
                      <td>
                        <p className="text-xs font-semibold text-navy-900">{record.filename || record.report_id}</p>
                        <p className="text-[11px] text-slate-500">
                          {record.size_bytes ? `${(record.size_bytes / 1024).toFixed(0)} KB` : '—'}
                          {record.scope?.role ? ` · ${humanise(record.scope.role)}` : ''}
                          {record.scope?.applicant_id ? ` · ${record.scope.applicant_id}` : ''}
                        </p>
                        {record.error ? <p className="text-[11px] text-red-600">{record.error}</p> : null}
                      </td>
                      <td className="text-xs text-slate-600">{humanise(record.kind)}</td>
                      <td className="text-xs text-slate-500">{formatDate(record.created_at)}</td>
                      <td className="text-xs text-slate-500">{record.created_by || 'system'}</td>
                      <td>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                            record.status === 'COMPLETED'
                              ? 'bg-emerald-50 text-emerald-700'
                              : record.status === 'FAILED'
                                ? 'bg-red-50 text-red-700'
                                : 'bg-amber-50 text-amber-700'
                          }`}
                        >
                          {record.status === 'PENDING' || record.status === 'RUNNING' ? <Clock className="h-3 w-3" /> : null}
                          {humanise(record.status)}
                        </span>
                      </td>
                      <td className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={record.status !== 'COMPLETED'}
                          onClick={() => void download(record)}
                        >
                          <Download className="h-3.5 w-3.5" /> Download
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-5">
              <EmptyState
                title="No reports generated yet"
                description="Generate an Excel workbook or PDF above. Completed reports appear here with a signed download link."
                icon={<FileSpreadsheet className="h-5 w-5" />}
              />
            </div>
          )
        ) : null}
      </Card>

      <p className="text-[11px] text-slate-400">
        Status colours: <span className="font-semibold text-emerald-700">Completed</span> ·{' '}
        <span className="font-semibold text-amber-700">Pending</span> ·{' '}
        <span className="font-semibold text-red-700">Failed</span>
      </p>
    </div>
  )
}
