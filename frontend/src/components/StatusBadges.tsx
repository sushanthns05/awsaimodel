import { Badge } from './ui/badge'
import { cn, formatScore, humanise, scoreTone } from '../lib/utils'
import type { ProcessingStatus, Recommendation, ReviewStatus } from '../types'

const RECOMMENDATION_VARIANT: Record<string, 'success' | 'info' | 'warning' | 'danger' | 'orange' | 'secondary'> = {
  STRONG_INTERVIEW: 'success',
  INTERVIEW_CONSIDERATION: 'info',
  MANUAL_REVIEW: 'warning',
  ELIGIBILITY_REVIEW: 'orange',
  NEEDS_REVIEW: 'danger',
}

const STATUS_VARIANT: Record<string, 'success' | 'info' | 'warning' | 'danger' | 'secondary'> = {
  COMPLETED: 'success',
  NEEDS_REVIEW: 'warning',
  FAILED: 'danger',
  RECEIVED: 'secondary',
  QUEUED: 'info',
  EXTRACTING: 'info',
  EXTRACTED: 'info',
  EVALUATING: 'info',
  SCORING: 'info',
  DELETED: 'danger',
}

const REVIEW_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'secondary'> = {
  APPROVED: 'success',
  MANUAL_REVIEW: 'warning',
  REJECTED: 'danger',
  PENDING: 'secondary',
}

export function ScoreBadge({ score, className }: { score: number; className?: string }) {
  const tone = scoreTone(score)
  const palette = {
    strong: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    good: 'border-sky-200 bg-sky-50 text-sky-800',
    review: 'border-amber-200 bg-amber-50 text-amber-800',
    low: 'border-red-200 bg-red-50 text-red-700',
  }[tone]
  return (
    <span className={cn('inline-flex min-w-[52px] items-center justify-center rounded-md border px-2 py-1 text-xs font-bold tabular-nums', palette, className)}>
      {formatScore(score)}
    </span>
  )
}

export function RecommendationBadge({ value }: { value: Recommendation | string }) {
  const variant = RECOMMENDATION_VARIANT[value] ?? 'secondary'
  const labels: Record<string, string> = {
    STRONG_INTERVIEW: 'Strong interview',
    INTERVIEW_CONSIDERATION: 'Interview consideration',
    MANUAL_REVIEW: 'Manual review',
    ELIGIBILITY_REVIEW: 'Eligibility review',
    NEEDS_REVIEW: 'Needs review',
  }
  return <Badge variant={variant}>{labels[value] ?? humanise(value)}</Badge>
}

export function StatusBadge({ value }: { value: ProcessingStatus | string }) {
  return <Badge variant={STATUS_VARIANT[value] ?? 'secondary'}>{humanise(value)}</Badge>
}

export function ReviewBadge({ value }: { value: ReviewStatus | string }) {
  return <Badge variant={REVIEW_VARIANT[value] ?? 'secondary'}>{humanise(value)}</Badge>
}

export function EligibilityBadge({ value }: { value: string }) {
  const variant = value === 'PASS' ? 'success' : value === 'FAIL' ? 'danger' : 'warning'
  const label = value === 'PASS' ? 'Eligible' : value === 'FAIL' ? 'Ineligible' : 'Unverified'
  return <Badge variant={variant}>{label}</Badge>
}
