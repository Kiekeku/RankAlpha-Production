'use client'

import { useEffect } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'

const LAST_NON_COMPARE_URL_KEY = 'rankalpha.lastNonCompareUrl'

function buildCurrentUrl(pathname: string, searchParams: URLSearchParams): string {
  const qs = searchParams.toString()
  return qs ? `${pathname}?${qs}` : pathname
}

function sanitizeReturnUrl(raw: string): string {
  try {
    const url = new URL(raw, window.location.origin)
    url.searchParams.delete('drawer')
    url.searchParams.delete('symbol')
    url.searchParams.delete('tab')
    const qs = url.searchParams.toString()
    return qs ? `${url.pathname}?${qs}` : url.pathname
  } catch {
    return raw
  }
}

export function RouteMemory() {
  const pathname = usePathname()
  const searchParams = useSearchParams()

  useEffect(() => {
    try {
      if (!pathname) return
      const current = buildCurrentUrl(pathname, searchParams)
      const sanitized = sanitizeReturnUrl(current)
      if (sanitized === '/compare' || sanitized.startsWith('/compare/')) return
      sessionStorage.setItem(LAST_NON_COMPARE_URL_KEY, sanitized)
    } catch {
      // ignore
    }
  }, [pathname, searchParams])

  return null
}
