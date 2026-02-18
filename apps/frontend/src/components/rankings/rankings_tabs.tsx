'use client'

import { usePathname, useSearchParams } from 'next/navigation'

import { buildPathWithSearchParams, cloneSearchParams } from '@/lib/url_search_params'
import { TabLink, TabNav } from '@/components/ui/tab-nav'

type TabKey = 'list'

function buildHref(pathname: string, searchParams: URLSearchParams): string {
  const params = cloneSearchParams(searchParams)
  params.delete('views')
  return buildPathWithSearchParams(pathname, params)
}

export function RankingsTabs({ className }: { className?: string }) {
  const pathname = usePathname() || '/rankings'
  const searchParams = useSearchParams()
  const tab: TabKey = 'list'

  const tabs: Array<{ key: TabKey; href: string; label: string }> = [
    { key: 'list', href: buildHref(pathname, searchParams), label: 'Rankings List' },
  ]

  return (
    <TabNav className={className} aria-label="Rankings sections">
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
