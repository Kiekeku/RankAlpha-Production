import type { TickerOrigin } from '@/lib/ticker_nav'

type NavSection = { label: string; href: string }

const SECTION_OVERVIEW: NavSection = { label: 'Overview', href: '/overview/nowcast' }
const SECTION_RANKINGS: NavSection = { label: 'Rankings', href: '/rankings' }
const SECTION_SCREENER: NavSection = { label: 'Screener', href: '/screener' }
const SECTION_AI: NavSection = { label: 'AI Feed', href: '/ai-analysis' }
const SECTION_COMPARE: NavSection = { label: 'Compare', href: '/compare' }
const SECTION_PORTFOLIO: NavSection = { label: 'Portfolio', href: '/portfolio' }
const SECTION_ADMIN: NavSection = { label: 'Admin', href: '/admin' }
const SECTION_ABOUT: NavSection = { label: 'About', href: '/about' }
const SECTION_METHOD: NavSection = { label: 'Methodology', href: '/methodology' }
const SECTION_DISCLAIMER: NavSection = { label: 'Disclaimer', href: '/disclaimer' }

function startsWithPath(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}

export function sectionFromOrigin(origin: TickerOrigin): NavSection {
  switch (origin) {
    case 'screener':
      return SECTION_SCREENER
    case 'ai-analysis':
      return SECTION_AI
    case 'compare':
      return SECTION_COMPARE
    case 'command':
      return SECTION_RANKINGS
    case 'rankings':
    default:
      return SECTION_RANKINGS
  }
}

export function sectionFromPath(pathname: string): NavSection {
  const path = (pathname || '/').split('?')[0].split('#')[0]
  if (startsWithPath(path, '/overview')) return SECTION_OVERVIEW
  if (startsWithPath(path, '/rankings') || startsWithPath(path, '/explore')) return SECTION_RANKINGS
  if (startsWithPath(path, '/screener') || startsWithPath(path, '/screeners')) return SECTION_SCREENER
  if (startsWithPath(path, '/ai-analysis')) return SECTION_AI
  if (startsWithPath(path, '/compare')) return SECTION_COMPARE
  if (startsWithPath(path, '/portfolio')) return SECTION_PORTFOLIO
  if (startsWithPath(path, '/admin')) return SECTION_ADMIN
  if (startsWithPath(path, '/about')) return SECTION_ABOUT
  if (startsWithPath(path, '/methodology')) return SECTION_METHOD
  if (startsWithPath(path, '/disclaimer')) return SECTION_DISCLAIMER
  return SECTION_RANKINGS
}

export function isInternalHref(href: string | null | undefined): href is string {
  return typeof href === 'string' && href.trim().startsWith('/')
}

export function buildBackLabel(section: NavSection, returnTo?: string | null): string {
  const hasQuery = Boolean(returnTo && returnTo.includes('?'))
  if (hasQuery && (section.label === 'Rankings' || section.label === 'Screener')) {
    return `Back to ${section.label} results`
  }
  return `Back to ${section.label}`
}

export function titleizeSlug(raw: string): string {
  const cleaned = raw.replace(/[_-]+/g, ' ').trim()
  if (!cleaned) return raw
  return cleaned
    .split(' ')
    .map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : ''))
    .join(' ')
}

export function labelFromTickerTab(tab: string): string {
  switch (tab) {
    case 'summary':
      return 'Summary'
    case 'technicals':
      return 'Technicals'
    case 'setups':
      return 'Setup hits'
    case 'ai':
      return 'AI Snapshot'
    case 'peers':
      return 'Peers'
    default:
      return titleizeSlug(tab)
  }
}

export type { NavSection }
