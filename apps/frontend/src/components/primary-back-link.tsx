'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { ArrowLeftIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import { buildBackLabel, isInternalHref, sectionFromOrigin, sectionFromPath } from '@/lib/navigation'
import { readTickerOrigin } from '@/lib/ticker_nav'

const LAST_NON_COMPARE_URL_KEY = 'rankalpha.lastNonCompareUrl'

type BackLinkState = {
  href: string
  label: string
}

function fallbackState(label: string, href: string): BackLinkState {
  return { href, label }
}

function resolveTickerBack(): BackLinkState {
  const { origin, returnTo } = readTickerOrigin()
  const section = sectionFromOrigin(origin)
  let href = returnTo && returnTo.startsWith('/') ? returnTo : null

  if (!href && typeof document !== 'undefined') {
    const referrer = document.referrer || ''
    if (referrer) {
      try {
        const url = new URL(referrer)
        if (url.origin === window.location.origin && !url.pathname.startsWith('/ticker')) {
          href = `${url.pathname}${url.search}`
        }
      } catch {
        // ignore invalid referrer
      }
    }
  }

  if (!href) href = section.href
  return { href, label: buildBackLabel(section, href) }
}

function resolveCompareBack(): BackLinkState {
  if (typeof window === 'undefined') {
    return fallbackState('Back to Rankings', '/rankings')
  }

  let href: string | null = null
  try {
    const v = sessionStorage.getItem(LAST_NON_COMPARE_URL_KEY)
    if (v && !v.startsWith('/compare')) href = v
  } catch {
    href = null
  }

  const section = sectionFromPath(href || '/rankings')
  const target = isInternalHref(href) ? href : section.href
  return { href: target, label: buildBackLabel(section, target) }
}

function resolveAiBack(): BackLinkState {
  return fallbackState('Back to AI Feed', '/ai-analysis')
}

export function PrimaryBackLink({
  kind,
  className,
}: {
  kind: 'ticker' | 'compare' | 'ai'
  className?: string
}) {
  const [state, setState] = useState<BackLinkState>(() => {
    if (kind === 'compare') return fallbackState('Back to Rankings', '/rankings')
    if (kind === 'ai') return resolveAiBack()
    return fallbackState('Back to Rankings', '/rankings')
  })

  useEffect(() => {
    if (kind === 'compare') {
      setState(resolveCompareBack())
      return
    }
    if (kind === 'ai') {
      setState(resolveAiBack())
      return
    }
    setState(resolveTickerBack())
  }, [kind])

  return (
    <Link
      href={state.href}
      className={cn(
        'inline-flex items-center gap-2 text-xs font-semibold text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        className,
      )}
    >
      <ArrowLeftIcon className="h-3.5 w-3.5" aria-hidden />
      {state.label}
    </Link>
  )
}
