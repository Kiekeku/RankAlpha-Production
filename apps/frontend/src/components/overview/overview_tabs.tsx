'use client'

import { usePathname } from 'next/navigation'
import { useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { TabLink, TabNav } from '@/components/ui/tab-nav'
import { FIVE_MIN_MS } from '@/lib/time'
import {
  MACRO_OVERVIEW_QUERY_KEY,
  NOWCAST_OVERVIEW_QUERY_KEY,
  REGIME_OVERVIEW_QUERY_KEY,
} from '@/components/home-overview-prefetch'

const tabs: Array<{ href: string; label: string }> = [
  { href: '/overview/nowcast', label: 'Risk Nowcast' },
  { href: '/overview/macro', label: 'Macro Dashboard' },
  { href: '/overview/regime', label: 'Regime Detail' },
]

export function OverviewTabs() {
  const pathname = usePathname()
  const queryClient = useQueryClient()
  const prefetched = useRef(new Set<string>())

  const prefetchOverview = useCallback(
    (href: string) => {
      if (prefetched.current.has(href)) return

      const config =
        href === '/overview/nowcast'
          ? { key: NOWCAST_OVERVIEW_QUERY_KEY, url: '/api/overview/nowcast' }
          : href === '/overview/macro'
          ? { key: MACRO_OVERVIEW_QUERY_KEY, url: '/api/overview/macro' }
          : href === '/overview/regime'
          ? { key: REGIME_OVERVIEW_QUERY_KEY, url: '/api/overview/regime' }
          : null

      if (!config) return
      prefetched.current.add(href)

      queryClient.prefetchQuery({
        queryKey: config.key,
        queryFn: async ({ signal }) => {
          const res = await fetch(config.url, { signal })
          if (!res.ok) throw new Error(`Failed to prefetch ${href}: ${res.status}`)
          return res.json()
        },
        staleTime: FIVE_MIN_MS,
      })
    },
    [queryClient]
  )

  return (
    <TabNav aria-label="Overview sections">
      {tabs.map((tab) => {
        const isActive = pathname === tab.href
        return (
          <TabLink
            key={tab.href}
            href={tab.href}
            onMouseEnter={() => prefetchOverview(tab.href)}
            onFocus={() => prefetchOverview(tab.href)}
            onTouchStart={() => prefetchOverview(tab.href)}
            aria-current={isActive ? 'page' : undefined}
            active={isActive}
          >
            {tab.label}
          </TabLink>
        )
      })}
    </TabNav>
  )
}
