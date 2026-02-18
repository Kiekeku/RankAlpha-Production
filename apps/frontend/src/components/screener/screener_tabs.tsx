'use client'

import { usePathname, useSearchParams } from 'next/navigation'

import { writeLocalStorageJson } from '@/lib/storage'
import { buildPathWithSearchParams, cloneSearchParams } from '@/lib/url_search_params'
import { TabLink, TabNav } from '@/components/ui/tab-nav'

type ScreenerTabKey = 'changes' | 'breadth' | 'results'

const SCREENER_TAB_STORAGE_KEY = 'rankalpha.screener.tab.v1'

function parseScreenerTab(searchParams: URLSearchParams): ScreenerTabKey {
  const raw = (searchParams.get('tab') || '').trim().toLowerCase()
  if (raw === 'changes' || raw === 'breadth' || raw === 'results') return raw
  return 'results'
}

function buildHref(pathname: string, searchParams: URLSearchParams, next: { tab?: ScreenerTabKey }): string {
  const params = cloneSearchParams(searchParams)
  params.delete('views')

  if (next.tab) {
    params.set('tab', next.tab)
  }

  return buildPathWithSearchParams(pathname, params)
}

export function ScreenerTabs({
  className,
  activeTab: activeTabProp,
  onPrefetch,
}: {
  className?: string
  activeTab?: ScreenerTabKey
  onPrefetch?: (tab: ScreenerTabKey) => void
}) {
  const pathname = usePathname() || '/screener'
  const searchParams = useSearchParams()

  const activeTab = activeTabProp ?? parseScreenerTab(searchParams)
  const tabs: Array<{ key: ScreenerTabKey; href: string; label: string }> = [
    { key: 'changes', href: buildHref(pathname, searchParams, { tab: 'changes' }), label: 'Movements' },
    { key: 'breadth', href: buildHref(pathname, searchParams, { tab: 'breadth' }), label: 'Breadth' },
    { key: 'results', href: buildHref(pathname, searchParams, { tab: 'results' }), label: 'Results' },
  ]

  return (
    <TabNav className={className} aria-label="Screener sections">
      {tabs.map((it) => {
        const isActive = activeTab === it.key
        return (
          <TabLink
            key={it.key}
            href={it.href}
            aria-current={isActive ? 'page' : undefined}
            onClick={() => {
              writeLocalStorageJson(SCREENER_TAB_STORAGE_KEY, { v: 1, tab: it.key })
            }}
            onMouseEnter={() => onPrefetch?.(it.key)}
            onFocus={() => onPrefetch?.(it.key)}
            onTouchStart={() => onPrefetch?.(it.key)}
            active={isActive}
          >
            {it.label}
          </TabLink>
        )
      })}

    </TabNav>
  )
}

export type { ScreenerTabKey }
