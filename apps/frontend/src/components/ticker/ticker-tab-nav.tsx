'use client'

import { TabLink, TabNav } from '@/components/ui/tab-nav'

const LAST_TAB_KEY = 'rankalpha.ticker.lastTab.v1'

export function TickerTabNav({
  tabs,
  activeTab,
  canonicalPath,
}: {
  tabs: Array<{ key: string; label: string }>
  activeTab: string
  canonicalPath: string
}) {
  const handleClick = (key: string) => {
    try {
      window.localStorage.setItem(LAST_TAB_KEY, key)
    } catch {
      // ignore storage failures
    }
  }

  return (
    <TabNav
      className="sticky top-0 z-20 border-b border-outline/10 bg-background/85 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/70"
      aria-label="Stock detail sections"
    >
      {tabs.map((it) => {
        const isActive = activeTab === it.key
        const hash = it.key === 'technicals' ? '#technicals-price' : ''
        const href = `${canonicalPath}?tab=${it.key}${hash}`
        return (
          <TabLink
            key={it.key}
            href={href}
            replace
            scroll={false}
            aria-current={isActive ? 'page' : undefined}
            active={isActive}
            onClick={() => handleClick(it.key)}
          >
            {it.label}
          </TabLink>
        )
      })}
    </TabNav>
  )
}
