import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Download, Filter, Search, X } from 'lucide-react'
import { api, type ApplicantFilters } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { formatDate, formatScore, humanise } from '../lib/utils'
import { EmptyState, ErrorState, PageLoader } from '../components/States'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Select } from '../components/ui/select'
import { Label } from '../components/ui/label'
import { ScoreBadge, RecommendationBadge, StatusBadge, EligibilityBadge, ReviewBadge } from '../components/StatusBadges'

const STATUSES = ['RECEIVED', 'QUEUED', 'EXTRACTING', 'EXTRACTED', 'EVALUATING', 'SCORING', 'COMPLETED', 'NEEDS_REVIEW', 'FAILED']
const RECOMMENDATIONS = ['STRONG_INTERVIEW', 'INTERVIEW_CONSIDERATION', 'MANUAL_REVIEW', 'ELIGIBILITY_REVIEW', 'NEEDS_REVIEW']
const REVIEW_STATUSES = ['PENDING', 'APPROVED', 'REJECTED', 'MANUAL_REVIEW']

export function ApplicantsPage() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [eligibility, setEligibility] = useState('')
  const [recommendation, setRecommendation] = useState('')
  const [reviewStatus, setReviewStatus] = useState('')
  const [minScore, setMinScore] = useState('')
  const [maxScore, setMaxScore] = useState('')
  const [sort, setSort] = useState('submitted_at')
  const [showFilters, setShowFilters] = useState(false)
  const [cursor, setCursor] = useState('')
  const [history, setHistory] = useState<string[]>([])
  const [exporting, setExporting] = useState(false)

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings, staleTime: 300_000 })
  const roles = settings?.roles?.roles ?? []

  const filters = useMemo<ApplicantFilters>(
    () => ({
      q: debouncedSearch,
      role,
      status,
      eligibility,
      recommendation,
      reviewStatus,
      minScore: minScore ? Number(minScore) : undefined,
      maxScore: maxScore ? Number(maxScore) : undefined,
      sort,
      pageSize: 25,
      cursor,
    }),
    [debouncedSearch, role, status, eligibility, recommendation, reviewStatus, minScore, maxScore, sort, cursor],
  )

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['applicants', filters],
    queryFn: () => api.applicants(filters),
    placeholderData: (previous) => previous,
  })

  function resetFilters() {
    setSearch('')
    setRole('')
    setStatus('')
    setEligibility('')
    setRecommendation('')
    setReviewStatus('')
    setMinScore('')
    setMaxScore('')
    setSort('submitted_at')
    setCursor('')
    setHistory([])
  }

  function nextPage() {
    if (!data?.nextCursor) return
    setHistory((prev) => [...prev, cursor])
    setCursor(data.nextCursor)
  }

  function previousPage() {
    const previous = history[history.length - 1] ?? ''
    setHistory((prev) => prev.slice(0, -1))
    setCursor(previous)
  }

  async function exportExcel() {
    setExporting(true)
    try {
      const record = await api.generateReport({ type: 'excel' })
      if (record.downloadUrl) window.open(record.downloadUrl, '_blank', 'noopener,noreferrer')
      else navigate('/reports')
    } finally {
      setExporting(false)
    }
  }

  const activeFilters = [role, status, eligibility, recommendation, reviewStatus, minScore, maxScore].filter(Boolean).length

  return (
    <div className="space-y-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-navy-900">Applicant directory</h2>
          <p className="mt-1 text-xs text-slate-500">
            Search, filter and inspect every application. AI scores are recommendations pending human review.
          </p>
        </div>
        {can('reports') ? (
          <Button variant="accent" size="sm" onClick={() => void exportExcel()} disabled={exporting}>
            <Download className="h-3.5 w-3.5" /> {exporting ? 'Preparing…' : 'Export Excel'}
          </Button>
        ) : null}
      </div>

      <Card>
        <CardContent className="space-y-3 p-4 pt-4">
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                className="pl-9"
                placeholder="Search name, email, USN, department or skills…"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  setCursor('')
                  setHistory([])
                }}
              />
              {search ? (
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:text-slate-700"
                  onClick={() => setSearch('')}
                  aria-label="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
            <div className="flex gap-2">
              <Select
                value={sort}
                onChange={(event) => {
                  setSort(event.target.value)
                  setCursor('')
                  setHistory([])
                }}
                className="w-[170px]"
                aria-label="Sort applicants"
              >
                <option value="submitted_at">Newest first</option>
                <option value="score">Highest score</option>
                <option value="name">Name (A–Z)</option>
              </Select>
              <Button variant="outline" onClick={() => setShowFilters((value) => !value)}>
                <Filter className="h-4 w-4" /> Filters
                {activeFilters ? (
                  <span className="ml-1 rounded-full bg-aws-orange px-1.5 text-[10px] font-bold text-navy-950">{activeFilters}</span>
                ) : null}
              </Button>
            </div>
          </div>

          {showFilters ? (
            <div className="grid gap-3 rounded-lg border border-slate-100 bg-slate-50/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-1">
                <Label>Role</Label>
                <Select value={role} onChange={(event) => { setRole(event.target.value); setCursor(''); setHistory([]) }}>
                  <option value="">All roles</option>
                  {roles.map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Processing status</Label>
                <Select value={status} onChange={(event) => { setStatus(event.target.value); setCursor(''); setHistory([]) }}>
                  <option value="">All statuses</option>
                  {STATUSES.map((item) => (
                    <option key={item} value={item}>{humanise(item)}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Eligibility</Label>
                <Select value={eligibility} onChange={(event) => { setEligibility(event.target.value); setCursor(''); setHistory([]) }}>
                  <option value="">All</option>
                  <option value="PASS">Eligible</option>
                  <option value="FAIL">Ineligible</option>
                  <option value="UNKNOWN">Unverified</option>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Recommendation</Label>
                <Select value={recommendation} onChange={(event) => { setRecommendation(event.target.value); setCursor(''); setHistory([]) }}>
                  <option value="">All</option>
                  {RECOMMENDATIONS.map((item) => (
                    <option key={item} value={item}>{humanise(item)}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Review status</Label>
                <Select value={reviewStatus} onChange={(event) => { setReviewStatus(event.target.value); setCursor(''); setHistory([]) }}>
                  <option value="">All</option>
                  {REVIEW_STATUSES.map((item) => (
                    <option key={item} value={item}>{humanise(item)}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Minimum score</Label>
                <Input type="number" min={0} max={100} placeholder="0" value={minScore} onChange={(event) => { setMinScore(event.target.value); setCursor(''); setHistory([]) }} />
              </div>
              <div className="space-y-1">
                <Label>Maximum score</Label>
                <Input type="number" min={0} max={100} placeholder="100" value={maxScore} onChange={(event) => { setMaxScore(event.target.value); setCursor(''); setHistory([]) }} />
              </div>
              <div className="flex items-end">
                <Button variant="ghost" size="sm" onClick={resetFilters}>
                  <X className="h-3.5 w-3.5" /> Clear filters
                </Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {isLoading ? <PageLoader label="Loading applicants…" /> : null}
      {isError ? <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} /> : null}

      {!isLoading && !isError && data ? (
        <Card>
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <p className="text-xs text-slate-500">
              Showing <span className="font-semibold text-navy-900">{data.count}</span> applicant{data.count === 1 ? '' : 's'}
              {isFetching ? <span className="ml-2 text-slate-400">updating…</span> : null}
            </p>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="sm" onClick={previousPage} disabled={!history.length}>
                <ChevronLeft className="h-3.5 w-3.5" /> Previous
              </Button>
              <Button variant="outline" size="sm" onClick={nextPage} disabled={!data.nextCursor}>
                Next <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          {data.items.length === 0 ? (
            <div className="p-6">
              <EmptyState
                title="No applicants match these filters"
                description="Adjust the search or filters, or wait for new Google Form submissions to arrive."
                action={<Button variant="outline" size="sm" onClick={resetFilters}>Clear filters</Button>}
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-grid">
                <thead>
                  <tr>
                    <th>Applicant</th>
                    <th>Roles</th>
                    <th className="hidden md:table-cell">Department</th>
                    <th className="hidden lg:table-cell">Submitted</th>
                    <th className="text-right">Score</th>
                    <th>Recommendation</th>
                    <th className="hidden sm:table-cell">Eligibility</th>
                    <th>Status</th>
                    <th className="hidden xl:table-cell">Review</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((applicant) => (
                    <tr
                      key={applicant.applicantId}
                      className="cursor-pointer"
                      onClick={() => navigate(`/applicants/${applicant.applicantId}`)}
                    >
                      <td>
                        <div className="min-w-[180px]">
                          <p className="font-semibold text-navy-900">{applicant.fullName || 'Unnamed applicant'}</p>
                          <p className="text-[11px] text-slate-500">{applicant.usn || applicant.email || applicant.applicantId}</p>
                          {applicant.urgentReview ? <span className="text-[10px] font-semibold text-orange-700">Flagged for review</span> : null}
                        </div>
                      </td>
                      <td>
                        <div className="flex max-w-[200px] flex-wrap gap-1">
                          {applicant.roles.map((item) => (
                            <span key={item} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                              {roles.find((r) => r.id === item)?.name ?? humanise(item)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="hidden md:table-cell text-xs text-slate-600">
                        {applicant.department || '—'}
                        <span className="block text-[11px] text-slate-400">Year {applicant.yearOfStudy || '—'}</span>
                      </td>
                      <td className="hidden lg:table-cell text-xs text-slate-500">{formatDate(applicant.submittedAt)}</td>
                      <td className="text-right"><ScoreBadge score={applicant.totalScore} /></td>
                      <td><RecommendationBadge value={applicant.recommendation} /></td>
                      <td className="hidden sm:table-cell"><EligibilityBadge value={applicant.eligibilityStatus} /></td>
                      <td><StatusBadge value={applicant.processingStatus} /></td>
                      <td className="hidden xl:table-cell"><ReviewBadge value={applicant.reviewStatus} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}

      <p className="text-[11px] text-slate-400">
        Scores are calculated from AI-proposed evidence-backed fractions using the active rubric ({settings?.rubric?.version ? String(settings.rubric.version) : '1.0.0'}).
        Average score is {formatScore(data?.items.reduce((sum, item) => sum + item.totalScore, 0) ?? 0)} on this page.
      </p>
    </div>
  )
}
