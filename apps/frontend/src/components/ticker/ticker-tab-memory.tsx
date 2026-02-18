'use client'

import { useEffect, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { readTickerOrigin } from '@/lib/ticker_nav'

const LAST_TAB_KEY = 'rankalpha.ticker.lastTab.v1'
const SUMMARY_SESSION_KEY = 'rankalpha.ticker.summarySelected.v1'

export function TickerTabMemory({ tabs }: { tabs: string[] }) {
  const pathname = usePathname()
  const router = useRouter()
  const searchParams = useSearchParams()

  const validTabs = useMemo(() => new Set(tabs.map((t) => t.toLowerCase())), [tabs])

  useEffect(() => {
    const raw = (searchParams.get('tab') || '').trim().toLowerCase()
    const normalized = validTabs.has(raw) ? raw : ''

    if (normalized) {
      try {
        window.localStorage.setItem(LAST_TAB_KEY, normalized)
        if (normalized === 'summary') {
          window.sessionStorage.setItem(SUMMARY_SESSION_KEY, '1')
        } else {
          window.sessionStorage.removeItem(SUMMARY_SESSION_KEY)
        }
      } catch {
        // ignore storage failures
      }
      return
    }

    const { origin } = readTickerOrigin()
    if (origin === 'ai-analysis' && validTabs.has('ai')) {
      const params = new URLSearchParams(searchParams.toString())
      params.set('tab', 'ai')
      const qs = params.toString()
      const next = qs ? `${pathname}?${qs}` : pathname
      router.replace(next)
      return
    }

    let stored: string | null = null
    let summarySelected = false
    try {
      stored = window.localStorage.getItem(LAST_TAB_KEY)
      summarySelected = window.sessionStorage.getItem(SUMMARY_SESSION_KEY) === '1'
    } catch {
      stored = null
      summarySelected = false
    }

    if (stored && validTabs.has(stored) && stored !== 'summary' && !summarySelected) {
      const params = new URLSearchParams(searchParams.toString())
      params.set('tab', stored)
      const qs = params.toString()
      const next = qs ? `${pathname}?${qs}` : pathname
      router.replace(next)
      return
    }

    if (!summarySelected) {
      try {
        window.sessionStorage.setItem(SUMMARY_SESSION_KEY, '1')
      } catch {
        // ignore storage failures
      }
    }
  }, [pathname, router, searchParams, validTabs])

  return null
}
