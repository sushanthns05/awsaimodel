import { useEffect, useState, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getStoredLiveApplicants, syncGoogleSheetFromUrl } from '../lib/googleSync'

export function useRealtimeSync(pollIntervalMs = 30000) {
  const queryClient = useQueryClient()
  const [isSyncing, setIsSyncing] = useState(false)
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(() => {
    return typeof window !== 'undefined' ? localStorage.getItem('sbg_last_synced_at') : null
  })
  const [applicantCount, setApplicantCount] = useState<number>(() => {
    return typeof window !== 'undefined' ? getStoredLiveApplicants().length : 0
  })
  const [syncError, setSyncError] = useState<string | null>(null)
  const isSyncingRef = useRef(false)

  const performSync = useCallback(
    async (showLoading = false) => {
      if (isSyncingRef.current || typeof window === 'undefined') return
      const sheetUrl = localStorage.getItem('sbg_last_sheet_url')
      if (!sheetUrl || !sheetUrl.trim()) {
        setApplicantCount(getStoredLiveApplicants().length)
        return
      }

      isSyncingRef.current = true
      if (showLoading) setIsSyncing(true)

      try {
        const res = await syncGoogleSheetFromUrl(sheetUrl, false)
        if (res.success) {
          setApplicantCount(res.applicants.length)
          const now = new Date().toISOString()
          setLastSyncedAt(now)
          setSyncError(null)
          void queryClient.invalidateQueries({ queryKey: ['overview'] })
          void queryClient.invalidateQueries({ queryKey: ['applicants'] })
          void queryClient.invalidateQueries({ queryKey: ['shortlist'] })
        } else if (showLoading) {
          setSyncError(res.error || 'Sync failed')
        }
      } catch (err) {
        if (showLoading) {
          setSyncError((err as Error).message)
        }
      } finally {
        isSyncingRef.current = false
        setIsSyncing(false)
      }
    },
    [queryClient]
  )

  useEffect(() => {
    // Initial fetch on mount
    void performSync(false)

    // Polling interval
    const interval = setInterval(() => {
      void performSync(false)
    }, pollIntervalMs)

    // Window focus refresh
    const onFocus = () => {
      void performSync(false)
    }
    window.addEventListener('focus', onFocus)

    // Custom sync event listener
    const onCustomSync = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.totalApplicants !== undefined) {
        setApplicantCount(detail.totalApplicants)
      }
      if (detail?.timestamp) {
        setLastSyncedAt(detail.timestamp)
      }
    }
    window.addEventListener('sbg:realtime-synced', onCustomSync)

    return () => {
      clearInterval(interval)
      window.removeEventListener('focus', onFocus)
      window.removeEventListener('sbg:realtime-synced', onCustomSync)
    }
  }, [performSync, pollIntervalMs])

  return {
    isSyncing,
    lastSyncedAt,
    applicantCount,
    syncError,
    triggerSync: () => performSync(true),
  }
}

