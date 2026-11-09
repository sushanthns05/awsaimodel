import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  Download,
  RefreshCw,
  Sparkles,
  UserCheck,
  Users,
  XCircle,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { formatDate, formatScore, initials } from '../lib/utils'
import { PageLoader, ErrorState, EmptyState } from '../components/States'
import { StatCard } from '../components/StatCard'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { ScoreBadge, RecommendationBadge, StatusBadge } from '../components/StatusBadges'
import { ScoreDistributionChart, ProcessingDonut, RoleBarChart } from '../components/charts/Charts'

export function OverviewPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['overview'],
    queryFn: api.overview,
    staleTime: 30_000,
  })

  async function exportExcel() {
    const record = await api.generateReport({ type: 'excel' })
    if (record.downloadUrl) {
      window.open(record.downloadUrl, '_blank', 'noopener,noreferrer')
    } else {
      navigate('/reports')
    }
  }

  if (isLoading) return <PageLoader label="Loading recruitment overview…" />
  if (isError || !data) return <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />

  const stats = data.stats

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-aws-orange">Recruitment cycle {data.organization?.cycle ?? '2026–27'}</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-navy-900">Application pipeline</h2>
          <p className="mt-1 text-xs text-slate-500">
            Last refreshed {formatDate(data.generatedAt)} · {stats.totalApplications.toLocaleString('en-IN')} applications received
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={() => navigate('/applicants')}>
            <Users className="h-3.5 w-3.5" /> View applicants
          </Button>
          {can('reports') ? (
            <Button variant="accent" size="sm" onClick={() => void exportExcel()}>
              <Download className="h-3.5 w-3.5" /> Export Excel
            </Button>
          ) : null}
        </div>
      </div>

      {data.truncated ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
          Dashboard statistics are computed from the most recent 10,000 applications. Use reports for the complete dataset.
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total applications" value={stats.totalApplications.toLocaleString('en-IN')} hint="All Google Form submissions" icon={Users} />
        <StatCard label="Processed" value={stats.processed.toLocaleString('en-IN')} hint={`${stats.pending} pending · ${stats.failed} failed`} icon={CheckCircle2} tone="success" />
        <StatCard label="Eligible" value={stats.eligible.toLocaleString('en-IN')} hint={`${stats.ineligible} flagged ineligible`} icon={UserCheck} tone="success" />
        <StatCard label="Requires review" value={stats.needsReview.toLocaleString('en-IN')} hint="Incomplete, ineligible or uncertain" icon={ClipboardCheck} tone="warning" />
        <StatCard label="Strong interview" value={stats.strongRecommendations.toLocaleString('en-IN')} hint={`${stats.interviewConsideration} for consideration`} icon={Sparkles} tone="orange" />
        <StatCard label="Approved shortlist" value={stats.approvedShortlist.toLocaleString('en-IN')} hint="Human-approved for interview" icon={CalendarClock} tone="success" />
        <StatCard label="Average score" value={formatScore(stats.averageScore)} hint="Across processed applications" icon={ArrowUpRight} />
        <StatCard label="Failed processing" value={stats.failed.toLocaleString('en-IN')} hint="Requires reprocessing" icon={XCircle} tone={stats.failed > 0 ? 'danger' : 'default'} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Score distribution</CardTitle>
            <CardDescription>Applicants grouped by final deterministic score band.</CardDescription>
          </CardHeader>
          <CardContent>
            <ScoreDistributionChart data={data.scoreDistribution} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Processing status</CardTitle>
            <CardDescription>Current pipeline state of every application.</CardDescription>
          </CardHeader>
          <CardContent>
            <ProcessingDonut data={data.processingStatus} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Applications by role</CardTitle>
            <CardDescription>Applicants may apply for more than one role; counts overlap.</CardDescription>
          </CardHeader>
          <CardContent>
            <RoleBarChart data={data.roleStats.filter((role) => role.applicants > 0).map((role) => ({ name: role.name, applicants: role.applicants }))} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Top processed applicants</CardTitle>
            <CardDescription>Highest scores, subject to human review.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.topApplicants.length === 0 ? (
              <EmptyState title="No processed applicants" description="Processed applications will appear here." />
            ) : (
              data.topApplicants.slice(0, 6).map((applicant) => (
                <Link
                  key={applicant.applicantId}
                  to={`/applicants/${applicant.applicantId}`}
                  className="flex items-center gap-3 rounded-lg border border-transparent px-2 py-2 transition-colors hover:border-slate-200 hover:bg-slate-50"
                >
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-navy-50 text-[11px] font-bold text-navy-800">
                    {initials(applicant.fullName)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-navy-900">{applicant.fullName || 'Unnamed applicant'}</p>
                    <p className="truncate text-[11px] text-slate-500">{applicant.department} · {applicant.usn || 'No USN'}</p>
                  </div>
                  <ScoreBadge score={applicant.totalScore} />
                </Link>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Role-wise statistics</CardTitle>
            <CardDescription>Eligibility and shortlist progress by team.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <table className="data-grid">
              <thead>
                <tr>
                  <th>Role</th>
                  <th className="text-right">Applicants</th>
                  <th className="text-right">Eligible</th>
                  <th className="text-right">Avg score</th>
                  <th className="text-right">Shortlisted</th>
                </tr>
              </thead>
              <tbody>
                {data.roleStats.filter((role) => role.applicants > 0).map((role) => (
                  <tr key={role.roleId}>
                    <td className="font-medium text-navy-900">{role.name}</td>
                    <td className="text-right tabular-nums">{role.applicants}</td>
                    <td className="text-right tabular-nums text-emerald-700">{role.eligible}</td>
                    <td className="text-right tabular-nums">{formatScore(role.averageScore)}</td>
                    <td className="text-right tabular-nums">{role.shortlisted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Recent applications</CardTitle>
              <CardDescription>Latest submissions received from Google Forms.</CardDescription>
            </div>
            <Button variant="link" size="sm" onClick={() => navigate('/applicants')}>
              View all <ArrowUpRight className="h-3.5 w-3.5" />
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.recentApplicants.length === 0 ? (
              <EmptyState title="Waiting for applications" description="Connect your Google Form via Apps Script to start receiving submissions." />
            ) : (
              data.recentApplicants.map((applicant) => (
                <Link
                  key={applicant.applicantId}
                  to={`/applicants/${applicant.applicantId}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2.5 hover:border-slate-200 hover:bg-slate-50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-navy-900">{applicant.fullName || 'Unnamed applicant'}</p>
                    <p className="text-[11px] text-slate-500">{formatDate(applicant.submittedAt)} · {applicant.roles.join(', ')}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge value={applicant.processingStatus} />
                    <RecommendationBadge value={applicant.recommendation} />
                  </div>
                </Link>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
