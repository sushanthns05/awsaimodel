import type { LucideIcon } from 'lucide-react'
import { cn } from '../lib/utils'

interface StatCardProps {
  label: string
  value: string | number
  hint?: string
  icon?: LucideIcon
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'orange'
  className?: string
}

const TONES = {
  default: 'bg-navy-50 text-navy-800',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-700',
  danger: 'bg-red-50 text-red-700',
  orange: 'bg-orange-50 text-orange-700',
}

const ACCENTS = {
  default: 'text-navy-900',
  success: 'text-emerald-700',
  warning: 'text-amber-800',
  danger: 'text-red-700',
  orange: 'text-orange-700',
}

export function StatCard({ label, value, hint, icon: Icon, tone = 'default', className }: StatCardProps) {
  return (
    <div className={cn('rounded-xl border border-slate-200 bg-white p-5 shadow-card', className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
          <p className={cn('mt-2 text-3xl font-bold tabular-nums tracking-tight', ACCENTS[tone])}>{value}</p>
          {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
        </div>
        {Icon ? (
          <div className={cn('rounded-lg p-2.5', TONES[tone])}>
            <Icon className="h-5 w-5" />
          </div>
        ) : null}
      </div>
    </div>
  )
}
