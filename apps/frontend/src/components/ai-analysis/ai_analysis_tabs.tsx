'use client'

import { usePathname, useSearchParams } from 'next/navigation'

import { buildPathWithSearchParams, cloneSearchParams } from '@/lib/url_search_params'
import { TabLink, TabNav } from '@/components/ui/tab-nav'

type TabKey = 'feed' | 'search'

function inferActiveTab(searchParams: URLSearchParams): TabKey {
  const mode = (searchParams.get('mode') || '').trim().toLowerCase()
  if (mode === 'search') return 'search'
  const symbol = (searchParams.get('symbol') || '').trim()
  return symbol ? 'search' : 'feed'
}

function buildHref(pathname: string, searchParams: URLSearchParams, nextTab: TabKey): string {
  const params = cloneSearchParams(searchParams)
  params.delete('page')
  params.delete('views')

  if (nextTab === 'feed') {
    params.delete('symbol')
    params.delete('mode')
  } else {
    params.set('mode', 'search')
  }

  return buildPathWithSearchParams(pathname, params)
}

export function AiAnalysisTabs({ className }: { className?: string }) {
  const pathname = usePathname() || '/ai-analysis'
  const searchParams = useSearchParams()
  const tab = inferActiveTab(searchParams)

  const tabs: Array<{ key: TabKey; href: string; label: string }> = [
    { key: 'feed', href: buildHref(pathname, searchParams, 'feed'), label: 'AI Feed' },
    { key: 'search', href: buildHref(pathname, searchParams, 'search'), label: 'AI Snapshot' },
  ]

  return (
    <TabNav className={className} aria-label="AI feed sections">
      {tabs.map((it) => {
        const isActive = tab === it.key
        return (
          <TabLink
            key={it.key}
            href={it.href}
            aria-current={isActive ? 'page' : undefined}
            active={isActive}
          >
            {it.label}
          </TabLink>
        )
      })}
    </TabNav>
  )
}
