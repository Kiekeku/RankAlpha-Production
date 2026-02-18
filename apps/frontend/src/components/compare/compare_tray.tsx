'use client'

import { ChevronUpIcon, GitCompare, Minimize2Icon, XIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { createPortal } from 'react-dom'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { useCompare, buildComparePageUrl } from '@/components/compare/compare_context'
import { COMPARE_TRAY_OPEN_EVENT } from '@/components/compare/compare_events'
import { cn } from '@/lib/utils'
import { readLocalStorageJson, removeLocalStorageItem, writeLocalStorageJson } from '@/lib/storage'

const COMPARE_TRAY_COLLAPSED_KEY = 'rankalpha.compareTrayCollapsed'
const LAST_NON_COMPARE_URL_KEY = 'rankalpha.lastNonCompareUrl'

function rememberReturnUrl() {
  try {
    if (window.location.pathname === '/compare' || window.location.pathname.startsWith('/compare/')) return
    const url = new URL(window.location.href)
    url.searchParams.delete('drawer')
    url.searchParams.delete('symbol')
    url.searchParams.delete('tab')
    const qs = url.searchParams.toString()
    const value = qs ? `${url.pathname}?${qs}` : url.pathname
    if (value === '/compare' || value.startsWith('/compare/')) return
    sessionStorage.setItem(LAST_NON_COMPARE_URL_KEY, value)
  } catch {
    // ignore
  }
}

export function CompareTray({ className }: { className?: string }) {
  const compare = useCompare()
  const [collapsed, setCollapsed] = useState(true)
  const [portalHost, setPortalHost] = useState<HTMLElement | null>(null)
  const prevCountRef = useRef(0)
  const hasPersistedRef = useRef(false)
  const lastScrollYRef = useRef(0)
  const isScrollingRef = useRef(false)

  useEffect(() => {
    removeLocalStorageItem('rankalpha.compareTrayHidden')
    const persisted = readLocalStorageJson<boolean>(COMPARE_TRAY_COLLAPSED_KEY)
    if (typeof persisted === 'boolean') {
      setCollapsed(persisted)
      hasPersistedRef.current = true
    }
  }, [])

  useEffect(() => {
    if (compare.symbols.length < 1) {
      setPortalHost(null)
      return
    }

    const readHost = () => document.querySelector('[data-rankalpha-compare-tray-host="1"]') as HTMLElement | null
    const update = () => {
      const next = readHost()
      setPortalHost((prev) => (prev === next ? prev : next))
    }

    update()
    const observer = new MutationObserver(update)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [compare.symbols.length])

  useEffect(() => {
    const handleOpen = () => {
      if (compare.symbols.length < 1) return
      setCollapsed(false)
    }
    window.addEventListener(COMPARE_TRAY_OPEN_EVENT, handleOpen)
    return () => window.removeEventListener(COMPARE_TRAY_OPEN_EVENT, handleOpen)
  }, [compare.symbols.length])

  useEffect(() => {
    const handleClose = () => setCollapsed(true)
    window.addEventListener('rankalpha:closeOverlays', handleClose)
    return () => window.removeEventListener('rankalpha:closeOverlays', handleClose)
  }, [])

  useEffect(() => {
    if (compare.symbols.length < 1) return
    lastScrollYRef.current = window.scrollY
    const onScroll = () => {
      if (isScrollingRef.current) return
      isScrollingRef.current = true
      requestAnimationFrame(() => {
        const current = window.scrollY
        const delta = current - lastScrollYRef.current
        if (Math.abs(delta) >= 14) {
          if (delta > 0) {
            if (!collapsed) setCollapsed(true)
          } else {
            if (collapsed) setCollapsed(false)
          }
          lastScrollYRef.current = current
        }
        isScrollingRef.current = false
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [collapsed, compare.symbols.length])

  useEffect(() => {
    writeLocalStorageJson(COMPARE_TRAY_COLLAPSED_KEY, collapsed)
  }, [collapsed])

  useEffect(() => {
    const prev = prevCountRef.current
    const next = compare.symbols.length
    prevCountRef.current = next
    if (prev < 1 && next >= 1 && !hasPersistedRef.current) {
      setCollapsed(true)
    }
  }, [compare.symbols.length])

  if (compare.symbols.length < 1) return null
  const remaining = Math.max(0, compare.max - compare.symbols.length)
  const compareHint =
    compare.symbols.length < 2
      ? `1 selected — add 1 more to compare`
      : remaining > 0
        ? `${compare.symbols.length} selected — add ${remaining} more to enable ${compare.max}-way compare`
        : `${compare.symbols.length} selected — ready`

  const href = buildComparePageUrl({
    symbols: compare.symbols,
    baseline: compare.baseline ?? (compare.symbols[0] ?? null),
    mode: 'table',
    deltas: compare.showDeltas,
  })

  const trayNode = (
    <div
      className={cn(
        'fixed bottom-4 left-4 z-[90] w-[min(460px,calc(100vw-2rem))]',
        'sm:bottom-5 sm:left-5',
        className,
      )}
      data-rankalpha-compare-tray="1"
      role="region"
      aria-label="Compare tray"
    >
      {collapsed ? (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            className="h-10 rounded-full border-outline/20 bg-card/90 px-4 text-xs font-semibold text-foreground shadow-sm backdrop-blur"
            onClick={() => setCollapsed(false)}
            aria-label={`Expand compare tray (${compare.symbols.length} of ${compare.max})`}
          >
            <GitCompare className="mr-2 h-4 w-4" aria-hidden />
            Compare {compare.symbols.length}
            <ChevronUpIcon className="ml-1.5 h-4 w-4" aria-hidden />
          </Button>
          <span className="hidden text-xs text-muted-foreground sm:inline">{compareHint}</span>
        </div>
      ) : (
        <div className="flex flex-col gap-2 rounded-2xl border border-outline/10 bg-card/90 p-ds-3 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-card/70">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-2 text-sm font-semibold">
              <GitCompare className="h-4 w-4" aria-hidden />
              Compare {compare.symbols.length}/{compare.max}
            </div>

            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              {compare.symbols.map((sym) => (
                <Badge key={sym} variant="secondary" className="gap-1.5 pl-2 pr-1.5 py-1 text-xs font-semibold">
                  <span className="tabular-nums">{sym}</span>
                  <button
                    type="button"
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-outline/10 bg-background/50 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    onClick={() => compare.removeSymbol(sym)}
                    aria-label={`Remove ${sym} from compare`}
                  >
                    <XIcon className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </Badge>
              ))}
            </div>

            <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto sm:justify-end">
              <IconButton
                label="Minimize compare tray"
                variant="outline"
                className="border-outline/10"
                onClick={() => setCollapsed(true)}
              >
                <Minimize2Icon className="h-4 w-4" aria-hidden />
              </IconButton>
              <Link
                href={href}
                onClick={() => rememberReturnUrl()}
                className={cn(
                  'inline-flex items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                  'bg-primary text-primary-foreground hover:bg-primary/90',
                  'h-9 rounded-full px-4 text-xs sm:text-sm',
                )}
              >
                Open Compare
              </Link>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-9 rounded-full px-4 text-xs sm:text-sm"
                onClick={() => compare.clear()}
              >
                Clear
              </Button>
            </div>
          </div>
          <div className="text-xs text-muted-foreground">{compareHint}</div>
        </div>
      )}
    </div>
  )

  return portalHost ? createPortal(trayNode, portalHost) : trayNode
}
