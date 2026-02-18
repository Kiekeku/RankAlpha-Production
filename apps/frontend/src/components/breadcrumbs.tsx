'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { usePathname, useSearchParams, type ReadonlyURLSearchParams } from 'next/navigation'
import { ChevronRight } from 'lucide-react'

import { cn } from '@/lib/utils'
import {
  labelFromTickerTab,
  sectionFromOrigin,
  sectionFromPath,
  titleizeSlug,
} from '@/lib/navigation'
import { readTickerOrigin, type TickerOrigin } from '@/lib/ticker_nav'

type Breadcrumb = { label: string; href?: string }

type BreadcrumbsProps = {
  className?: string
  override?: Breadcrumb[]
  hideOnPaths?: string[]
}

function parseSymbolFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/ticker\/([^/]+)/i)
  if (match?.[1]) return decodeURIComponent(match[1]).toUpperCase()
  return null
}

function parseAiSymbolFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/ai-analysis\/([^/]+)/i)
  if (match?.[1]) {
    const raw = decodeURIComponent(match[1])
    if (raw.toLowerCase() === 'id') return null
    return raw.toUpperCase()
  }
  return null
}

function parseScreenerStyleFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/screener\/([^/]+)/i)
  if (match?.[1]) return titleizeSlug(decodeURIComponent(match[1]))
  return null
}

function parseOverviewTab(pathname: string): string | null {
  const match = pathname.match(/^\/overview\/([^/]+)/i)
  if (match?.[1]) return titleizeSlug(decodeURIComponent(match[1]))
  return null
}

function parseAboutSubpage(pathname: string): string | null {
  const match = pathname.match(/^\/about\/([^/]+)/i)
  const slug = match?.[1] ? decodeURIComponent(match[1]).toLowerCase() : ''
  if (!slug) return null
  const labels: Record<string, string> = {
    'factors': 'Factor Methodology',
    'nowcast': 'Risk Nowcast',
    'regime': 'Regime Detection',
    'screeners': 'Screener Methodology',
    'pipeline': 'Pipeline Health',
    'architecture': 'Architecture',
    'ai-analysis': 'AI Memos',
  }
  return labels[slug] ?? titleizeSlug(slug)
}

function parseMethodologySubpage(pathname: string): string | null {
  if (pathname === '/methodology') return 'Methodology Overview'
  const match = pathname.match(/^\/methodology\/([^/]+)/i)
  const slug = match?.[1] ? decodeURIComponent(match[1]).toLowerCase() : ''
  if (!slug) return null
  const labels: Record<string, string> = {
    'factors': 'Factor Methodology',
    'screeners': 'Screener Methodology',
    'ai-analysis': 'AI Memos',
  }
  return labels[slug] ?? titleizeSlug(slug)
}

function parseAiSection(searchParams: ReadonlyURLSearchParams): string | null {
  const mode = (searchParams.get('mode') || '').trim().toLowerCase()
  if (mode === 'search') return 'AI Snapshot'
  return 'AI Feed'
}

function parseScreenerTab(searchParams: ReadonlyURLSearchParams): string | null {
  const tab = (searchParams.get('tab') || '').trim().toLowerCase()
  if (tab === 'changes') return 'Movements'
  if (tab === 'breadth') return 'Breadth'
  if (tab === 'results') return 'Results'
  return 'Results'
}

function parseRankingsTab(): string | null {
  return 'Rankings List'
}

function buildDynamicBreadcrumbs(pathname: string, searchParams: ReadonlyURLSearchParams): Breadcrumb[] {
  const section = sectionFromPath(pathname)
  const crumbs: Breadcrumb[] = [section]

  if (pathname.startsWith('/overview')) {
    const tab = parseOverviewTab(pathname)
    if (tab && tab.toLowerCase() !== 'nowcast') {
      crumbs.push({ label: tab })
    }
    return crumbs
  }

  if (pathname.startsWith('/about')) {
    const subpage = parseAboutSubpage(pathname)
    if (subpage) crumbs.push({ label: subpage })
    return crumbs
  }

  if (pathname.startsWith('/methodology')) {
    const subpage = parseMethodologySubpage(pathname)
    if (subpage) crumbs.push({ label: subpage })
    return crumbs
  }

  if (pathname.startsWith('/rankings')) {
    const tab = parseRankingsTab()
    if (tab) crumbs.push({ label: tab })
    return crumbs
  }

  if (pathname.startsWith('/screener')) {
    const style = parseScreenerStyleFromPath(pathname)
    if (style) {
      crumbs.push({ label: 'Styles', href: '/screener' })
      crumbs.push({ label: style })
      return crumbs
    }
    const tab = parseScreenerTab(searchParams)
    if (tab) crumbs.push({ label: tab })
    return crumbs
  }

  if (pathname.startsWith('/ai-analysis')) {
    if (pathname.startsWith('/ai-analysis/id/')) {
      crumbs.push({ label: 'AI Memo' })
      return crumbs
    }
    const symbol = parseAiSymbolFromPath(pathname)
    if (symbol) {
      crumbs.push({ label: symbol })
      crumbs.push({ label: 'AI Memo' })
      return crumbs
    }
    const tab = parseAiSection(searchParams)
    if (tab) crumbs.push({ label: tab })
    return crumbs
  }

  if (pathname.startsWith('/compare')) return crumbs

  if (pathname.startsWith('/portfolio')) {
    crumbs.push({ label: 'Overview' })
    return crumbs
  }

  if (pathname.startsWith('/admin')) {
    crumbs.push({ label: 'Console' })
    return crumbs
  }

  return crumbs
}

function buildTickerBreadcrumbs(
  searchParams: ReadonlyURLSearchParams,
  pathname: string,
  origin: TickerOrigin,
  returnTo: string | null,
): Breadcrumb[] {
  const rawSymbol = parseSymbolFromPath(pathname)
  const symbol = rawSymbol || 'Ticker'
  const tab = (searchParams.get('tab') || 'summary').toLowerCase()
  const tabLabel = labelFromTickerTab(tab)
  const section = sectionFromOrigin(origin)
  const baseHref = returnTo && returnTo.startsWith('/') ? returnTo : section.href
  const base = { ...section, href: baseHref }

  const canonical = rawSymbol ? `/ticker/${encodeURIComponent(rawSymbol)}` : '/ticker'
  return [base, { label: symbol, href: canonical }, { label: tabLabel }]
}

export function Breadcrumbs({ className, override, hideOnPaths }: BreadcrumbsProps) {
  const pathname = usePathname() || ''
  const searchParams = useSearchParams()
  const [tickerOrigin, setTickerOrigin] = useState<{ origin: TickerOrigin; returnTo: string | null }>({
    origin: 'unknown',
    returnTo: null,
  })

  useEffect(() => {
    setTickerOrigin(readTickerOrigin())
  }, [])

  if (hideOnPaths?.some((p) => pathname.startsWith(p))) return null

  const crumbs = override ??
    (pathname.startsWith('/ticker')
      ? buildTickerBreadcrumbs(searchParams, pathname, tickerOrigin.origin, tickerOrigin.returnTo)
      : buildDynamicBreadcrumbs(pathname, searchParams))

  if (!crumbs.length) return null

  return (
    <div className={cn('flex items-center gap-1 text-[11px] text-muted-foreground', className)}>
      <span className="rounded-full border border-outline/10 bg-secondary/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        You are here
      </span>
      {crumbs.map((crumb, index) => {
        const isLast = index === crumbs.length - 1
        const canLink = Boolean(crumb.href) && !isLast
        const content = canLink ? (
          <Link
            href={crumb.href as string}
            className="inline-flex items-center gap-1 rounded-full px-2 py-1 font-semibold text-foreground/80 transition hover:text-foreground"
          >
            {crumb.label}
          </Link>
        ) : (
          <span
            aria-current={isLast ? 'page' : undefined}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2 py-1 font-semibold',
              isLast ? 'text-foreground' : 'text-foreground/80',
            )}
          >
            {crumb.label}
          </span>
        )

        return (
          <div key={`${crumb.label}-${index}`} className="flex items-center gap-1">
            {content}
            {!isLast ? <ChevronRight className="h-3 w-3 text-muted-foreground/60" aria-hidden /> : null}
          </div>
        )
      })}
    </div>
  )
}
