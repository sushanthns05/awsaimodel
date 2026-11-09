import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  ListChecks,
  Search,
  Trophy,
  Users,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { formatScore, humanise } from '../lib/utils'
import { EmptyState, ErrorState, PageLoader } from '../components/States'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Select } from '../components/ui/select'
import { Label } from '../components/ui/label'
import { Textarea } from '../components/ui/textarea'
import { Dialog } from '../components/ui/dialog'
import { ScoreBadge, RecommendationBadge, ReviewBadge, EligibilityBadge } from '../components/StatusBadges'
import type { ShortlistItem } from '../types'

type SortKey = 'roleScore' | 'totalScore' | 'rank' | 'fullName'

export function ShortlistPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { can } = useAuth()
  const [role, setRole] = useState('')
  const [minScore, setMinScore] = useState('')
  const [maxScore, setMaxScore] = useState('')
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [sortKey, setSortKey] = useState<SortKey>('roleScore')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [decision, setDecision] = useState('SHORTLISTED')
  const [notes, setNotes] = useState('')
  const [reason, setReason] = useState('')
  const [resultMessage, setResultMessage] = useState('')
  const [actionError, setActionError] = useState('')

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings, staleTime: 300_000 })
  const roles = settings?.roles.roles ?? []

  const queryParams = useMemo(
    () => ({
      role,
      minScore: minScore ? Number(minScore) : undefined,
      maxScore: maxScore ? Number(maxScore) : undefined,
      limit: 300,
    }),
    [role, minScore, maxScore],
  )

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['shortlist', queryParams],
    queryFn: () => api.shortlist(queryParams),
    placeholderData: (previous) => previous,
  })

  const bulkMutation = useMutation({
    mutationFn: () =>
      api.bulkDecision({
        applicantIds: Array.from(selected),
        decision,
        notes,
        reason,
      }),
    onSuccess: (result) => {
      setDialogOpen(false)
      setSelected(new Set())
      setNotes('')
      setReason('')
      setResultMessage(
        `${result.updated.length} applicant${result.updated.length === 1 ? '' : 's'} updated${
          result.skipped.length ? `, ${result.skipped.length} skipped` : ''
        }.`,
      )
      setActionError('')
      void queryClient.invalidateQueries({ queryKey: ['shortlist'] })
      void queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const items = useMemo(() => {
    const list = [...(data?.items ?? [])]
    const term = debouncedSearch.trim().toLowerCase()
    const filtered = term
      ? list.filter(
          (item) =>
            item.fullName.toLowerCase().includes(term) ||
            item.email.toLowerCase().includes(term) ||
            item.usn.toLowerCase().includes(term) ||
            item.applicantId.toLowerCase().includes(term),
        )
      : list
    filtered.sort((a, b) => {
      if (sortKey === 'fullName') return a.fullName.localeCompare(b.fullName)
      if (sortKey === 'rank') return a.rank - b.rank
      if (sortKey === 'totalScore') return b.totalScore - a.totalScore
      return b.roleScore - a.roleScore
    })
    return filtered
  }, [data?.items, debouncedSearch, sortKey])

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected((prev) => {
      if (prev.size === items.length) return new Set()
      return new Set(items.map((item) => item.applicantId))
    })
  }

  function openBulk(nextDecision: string) {
    if (!selected.size) return
    setDecision(nextDecision)
    setReason('')
    setNotes('')
    setActionError('')
    setDialogOpen(true)
  }

  async function exportRolePdf() {
    if (!role) return
    const record = await api.generateReport({ type: 'pdf_role', scope: { role } })
    if (record.downloadUrl) window.open(record.downloadUrl, '_blank', 'noopener,noreferrer')
    else navigate('/reports')
  }

  const flaggedSelected = items.filter(
    (item) => selected.has(item.applicantId) && (item.eligibilityStatus === 'FAIL' || item.urgentReview),
  ).length

  return (
    <div className="space-y-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-navy-900">Shortlisting & ranking</h2>
          <p className="mt-1 text-xs text-slate-500">
            Rank applicants by role-weighted score, then approve the interview shortlist. Every decision is attributed and audited.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {role ? (
            <Button variant="outline" size="sm" onClick={() => void exportRolePdf()}>
              <Download className="h-3.5 w-3.5" /> Role PDF
            </Button>
          ) : null}
          {can('shortlist') ? (
            <>
              <Button variant="outline" size="sm" onClick={() => openBulk('REJECTED')} disabled={!selected.size}>
                <AlertTriangle className="h-3.5 w-3.5" /> Reject selected
              </Button>
              <Button variant="accent" size="sm" onClick={() => openBulk('SHORTLISTED')} disabled={!selected.size}>
                <CheckCircle2 className="h-3.5 w-3.5" /> Approve selected
              </Button>
            </>
          ) : null}
        </div>
      </div>

      {resultMessage ? (
        <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          <CheckCircle2 className="h-4 w-4" /> {resultMessage}
        </div>
      ) : null}
      {actionError ? (
        <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {actionError}
        </div>
      ) : null}

      <Card>
        <CardContent className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
          <div className="space-y-1">
            <Label>Role</Label>
            <Select value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="">All roles (best role score)</option>
              {roles.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Minimum score</Label>
            <Input type="number" min={0} max={100} placeholder="0" value={minScore} onChange={(event) => setMinScore(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Maximum score</Label>
            <Input type="number" min={0} max={100} placeholder="100" value={maxScore} onChange={(event) => setMaxScore(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Sort by</Label>
            <Select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
              <option value="roleScore">Role score (highest)</option>
              <option value="totalScore">Total score (highest)</option>
              <option value="rank">Rank</option>
              <option value="fullName">Name (A–Z)</option>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input className="pl-9" placeholder="Name, USN, email…" value={search} onChange={(event) => setSearch(event.target.value)} />
            </div>
          </div>
        </CardContent>
      </Card>

      {isLoading ? <PageLoader label="Building the shortlist…" /> : null}
      {isError ? <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} /> : null}

      {!isLoading && !isError && data ? (
        <Card>
          <CardHeader className="flex-row items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Trophy className="h-4 w-4 text-aws-orange" />
                {role ? `${roles.find((item) => item.id === role)?.name ?? humanise(role)} ranking` : 'Overall ranking'}
              </CardTitle>
              <CardDescription>
                {data.total} applicant{data.total === 1 ? '' : 's'} eligible for ranking
                {selected.size ? ` · ${selected.size} selected${flaggedSelected ? ` (${flaggedSelected} flagged)` : ''}` : ''}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <ListChecks className="h-3.5 w-3.5" /> Ranked by deterministic score
            </div>
          </CardHeader>

          {items.length === 0 ? (
            <div className="p-6">
              <EmptyState
                title="No applicants to rank"
                description="Once applications finish processing they appear here ranked by score. Adjust the filters if needed."
                icon={<Users className="h-5 w-5" />}
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-grid">
                <thead>
                  <tr>
                    <th className="w-10">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300"
                        checked={items.length > 0 && selected.size === items.length}
                        onChange={toggleAll}
                        aria-label="Select all applicants"
                      />
                    </th>
                    <th className="w-12">#</th>
                    <th>Applicant</th>
                    <th>Roles</th>
                    <th className="text-right">Role score</th>
                    <th className="text-right">Total</th>
                    <th>Recommendation</th>
                    <th className="hidden sm:table-cell">Eligibility</th>
                    <th className="hidden xl:table-cell">Review</th>
                    <th className="hidden lg:table-cell">Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <ShortlistRow
                      key={item.applicantId}
                      item={item}
                      selected={selected.has(item.applicantId)}
                      onToggle={() => toggle(item.applicantId)}
                      onOpen={() => navigate(`/applicants/${item.applicantId}`)}
                      roleNames={roles}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title={decision === 'SHORTLISTED' ? 'Approve selected applicants' : 'Reject selected applicants'}
        description={`${selected.size} applicant${selected.size === 1 ? '' : 's'} will be updated. A written reason is required when overriding flags.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button
              variant={decision === 'SHORTLISTED' ? 'accent' : 'destructive'}
              onClick={() => bulkMutation.mutate()}
              disabled={bulkMutation.isPending}
            >
              {decision === 'SHORTLISTED' ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
              {bulkMutation.isPending ? 'Saving…' : decision === 'SHORTLISTED' ? 'Approve shortlist' : 'Reject applicants'}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>Reviewer notes</Label>
            <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Panel notes, interview focus, conditions…" />
          </div>
          <div className="space-y-1">
            <Label>
              Reason for overriding the recommendation <span className="text-red-600">*</span>
            </Label>
            <Textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain why these applicants should be approved or rejected despite the AI recommendation." />
          </div>
          {flaggedSelected ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
              {flaggedSelected} selected applicant{flaggedSelected === 1 ? ' is' : 's are'} ineligible or incomplete. A written reason is required.
            </div>
          ) : null}
        </div>
      </Dialog>
    </div>
  )
}

function ShortlistRow({
  item,
  selected,
  onToggle,
  onOpen,
  roleNames,
}: {
  item: ShortlistItem
  selected: boolean
  onToggle: () => void
  onOpen: () => void
  roleNames: { id: string; name: string }[]
}) {
  return (
    <tr className={selected ? 'bg-orange-50/40' : undefined}>
      <td>
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-slate-300"
          checked={selected}
          onChange={onToggle}
          aria-label={`Select ${item.fullName}`}
        />
      </td>
      <td className="text-xs font-semibold tabular-nums text-slate-500">{item.rank}</td>
      <td>
        <button type="button" className="text-left" onClick={onOpen}>
          <p className="font-semibold text-navy-900 hover:underline">{item.fullName || 'Unnamed applicant'}</p>
          <p className="text-[11px] text-slate-500">{item.usn || item.email || item.applicantId}</p>
          {item.urgentReview ? <span className="text-[10px] font-semibold text-orange-700">Flagged for review</span> : null}
        </button>
      </td>
      <td>
        <div className="flex max-w-[180px] flex-wrap gap-1">
          {item.roles.map((roleId) => (
            <span key={roleId} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
              {roleNames.find((role) => role.id === roleId)?.name ?? humanise(roleId)}
            </span>
          ))}
        </div>
      </td>
      <td className="text-right"><ScoreBadge score={item.roleScore} /></td>
      <td className="text-right text-sm font-semibold tabular-nums text-navy-900">{formatScore(item.totalScore)}</td>
      <td><RecommendationBadge value={item.recommendation} /></td>
      <td className="hidden sm:table-cell"><EligibilityBadge value={item.eligibilityStatus} /></td>
      <td className="hidden xl:table-cell"><ReviewBadge value={item.reviewStatus} /></td>
      <td className="hidden lg:table-cell">
        <div className="max-w-[240px] space-y-1">
          {item.strongestEvidence.slice(0, 1).map((evidence) => (
            <p key={evidence} className="line-clamp-2 text-[11px] leading-snug text-slate-600">{evidence}</p>
          ))}
          {item.concerns.slice(0, 1).map((concern) => (
            <p key={concern} className="line-clamp-1 text-[11px] leading-snug text-amber-700">{concern}</p>
          ))}
        </div>
      </td>
    </tr>
  )
}
