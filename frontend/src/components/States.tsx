import type { ReactNode } from 'react'
import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react'
import { Button } from './ui/button'
import { cn } from '../lib/utils'

export function PageLoader({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex min-h-[240px] flex-col items-center justify-center gap-3 text-slate-500">
      <Loader2 className="h-6 w-6 animate-spin text-navy-700" />
      <p className="text-sm">{label}</p>
    </div>
  )
}

export function ErrorState({
  message = 'Something went wrong.',
  onRetry,
  className,
}: {
  message?: string
  onRetry?: () => void
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50/60 px-6 py-10 text-center', className)}>
      <AlertTriangle className="h-6 w-6 text-red-600" />
      <div>
        <p className="text-sm font-semibold text-red-800">Unable to load this data</p>
        <p className="mt-1 max-w-lg text-xs text-red-700">{message}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" /> Try again
        </Button>
      ) : null}
    </div>
  )
}

export function EmptyState({
  title = 'Nothing here yet',
  description,
  action,
  icon,
}: {
  title?: string
  description?: string
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50/70 px-6 py-12 text-center">
      <div className="rounded-full bg-white p-3 text-slate-400 shadow-sm">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <div>
        <p className="text-sm font-semibold text-navy-900">{title}</p>
        {description ? <p className="mx-auto mt-1 max-w-md text-xs text-slate-500">{description}</p> : null}
      </div>
      {action}
    </div>
  )
}
