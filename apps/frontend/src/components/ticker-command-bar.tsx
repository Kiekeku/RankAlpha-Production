'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { BookmarkIcon, GitCompare, LayoutGridIcon, LineChartIcon, LinkIcon, SearchIcon, Wand2Icon } from 'lucide-react'
import { api, type OptionCount, type StockGradeItem } from '@/lib/api'
import { cn } from '@/lib/utils'
import { slugify } from '@/lib/slug'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from '@/components/ui/command'
import { useToast } from '@/components/ui/use-toast'
import { addRecentTicker, addSavedView, listRecentTickers, listSavedViews, removeSavedView } from '@/lib/command_bar'
import { FIVE_MIN_MS } from '@/lib/time'
import { buildComparePageUrl, useCompare } from '@/components/compare/compare_context'
import { openCompareTray } from '@/components/compare/compare_events'
import { rememberTickerOrigin } from '@/lib/ticker_nav'

type StockSearchRow = Pick<StockGradeItem, 'symbol' | 'company_name' | 'sector' | 'overall_grade'>

function isMacLike(): boolean {
  if (typeof navigator === 'undefined') return false
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform)
}

function shortcutHint(): string {
  return isMacLike() ? '⌘ K /' : 'Ctrl K /'
}

function normalizeTickerCandidate(raw: string): string {
  const upper = (raw || '').trim().toUpperCase()
  if (!upper) return ''
  if (!/^[A-Z0-9.]+$/.test(upper)) return ''
  if (upper.length < 1 || upper.length > 6) return ''
  return upper
}

function labelForRoute(pathname: string): string {
  if (pathname === '/' || pathname.startsWith('/overview')) return 'Overview'
  if (pathname.startsWith('/rankings')) return 'Rankings'
  if (pathname.startsWith('/screener')) return 'Screener'
  if (pathname.startsWith('/ai-analysis')) return 'AI Feed'
  if (pathname.startsWith('/portfolio')) return 'Portfolio'
  if (pathname.startsWith('/admin')) return 'Admin'
  if (pathname.startsWith('/about')) return 'About'
  return pathname
}

export function TickerCommandBar({ className }: { className?: string }) {
  const router = useRouter()
  const pathname = usePathname()
  const { toast } = useToast()
  const compare = useCompare()
  const actionGateRef = useRef(0)
  const pendingTickerRef = useRef<string | null>(null)
  const pendingTickerTimeoutRef = useRef<number | null>(null)
  const openRef = useRef(false)

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [recents, setRecents] = useState(() => listRecentTickers())
  const [savedViews, setSavedViews] = useState(() => listSavedViews())

  const tickerCandidate = useMemo(() => normalizeTickerCandidate(query), [query])

  const debouncedQuery = useDebouncedValue(query, 150)
  const searchText = debouncedQuery.trim()

  const { data: tickerResults, isLoading: tickerLoading } = useQuery({
    queryKey: ['commandbar-ticker-search', searchText],
    queryFn: async () => {
      if (!searchText) return []
      const res = await api.getStockGrades({ search: searchText, limit: 18, skip: 0 })
      const stocks = Array.isArray(res?.stocks) ? res.stocks : []
      return stocks.map((s) => ({
        symbol: s.symbol,
        company_name: s.company_name,
        sector: s.sector,
        overall_grade: s.overall_grade,
      })) as StockSearchRow[]
    },
    enabled: open && searchText.length > 0,
    staleTime: 10_000,
  })

  const { data: styleMeta } = useQuery({
    queryKey: ['commandbar-screener-styles-meta'],
    queryFn: () => api.listScreenerStylesMeta({ bias: 'all' }),
    enabled: open,
    staleTime: FIVE_MIN_MS,
  })

  const filteredStyles = useMemo(() => {
    const items: OptionCount[] = Array.isArray(styleMeta) ? styleMeta : []
    const q = searchText.toLowerCase()
    if (!q) return items.slice(0, 10)
    return items
      .filter((it) => (it?.name || '').toLowerCase().includes(q))
      .slice(0, 10)
  }, [styleMeta, searchText])

  useEffect(() => {
    if (!open) return
    setRecents(listRecentTickers())
    setSavedViews(listSavedViews())
  }, [open])

  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      const isK = (e.key || '').toLowerCase() === 'k'
      if (!isK) return
      if (!(e.metaKey || e.ctrlKey)) return
      e.preventDefault()
      setOpen(true)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    const handleOpen = () => setOpen(true)
    const handleClose = () => setOpen(false)
    window.addEventListener('rankalpha:openCommandBar', handleOpen)
    window.addEventListener('rankalpha:closeOverlays', handleClose)
    return () => {
      window.removeEventListener('rankalpha:openCommandBar', handleOpen)
      window.removeEventListener('rankalpha:closeOverlays', handleClose)
    }
  }, [])

  const close = () => setOpen(false)

  const clearPendingTicker = useCallback(() => {
    pendingTickerRef.current = null
    if (pendingTickerTimeoutRef.current != null && typeof window !== 'undefined') {
      window.clearTimeout(pendingTickerTimeoutRef.current)
      pendingTickerTimeoutRef.current = null
    }
  }, [])

  const setPendingTicker = useCallback((symbol: string) => {
    pendingTickerRef.current = symbol
    if (pendingTickerTimeoutRef.current != null && typeof window !== 'undefined') {
      window.clearTimeout(pendingTickerTimeoutRef.current)
    }
    if (typeof window !== 'undefined') {
      pendingTickerTimeoutRef.current = window.setTimeout(() => {
        pendingTickerRef.current = null
        pendingTickerTimeoutRef.current = null
      }, 2000)
    }
  }, [])

  const runCommandAction = (action: () => void) => {
    const now = Date.now()
    if (now - actionGateRef.current < 250) return
    actionGateRef.current = now
    action()
  }

  const commandActionProps = (action: () => void) => ({
    onSelect: () => runCommandAction(action),
    onClick: () => runCommandAction(action),
  })

  const go = (href: string) => {
    close()
    router.push(href)
  }

  const track = (symbol: string, companyName?: string) => {
    addRecentTicker({ symbol, company_name: companyName })
    setRecents(listRecentTickers())
  }

  const saveCurrentView = async () => {
    const label = `Saved - ${labelForRoute(pathname)}`
    const url =
      typeof window === 'undefined'
        ? pathname
        : `${window.location.pathname || pathname}${window.location.search || ''}`
    const saved = addSavedView({ url, name: label })
    setSavedViews(listSavedViews())
    if (saved) {
      toast({ title: 'View saved', description: label })
    } else {
      toast({ title: 'Could not save view', description: 'Try again.' })
    }
    close()
  }

  const copyCurrentLink = async () => {
    try {
      const href = typeof window === 'undefined' ? pathname : window.location.href
      await navigator.clipboard.writeText(href)
      toast({ title: 'Link copied', description: href })
    } catch {
      toast({ title: 'Copy failed', description: 'Clipboard unavailable.' })
    }
    close()
  }

  const goToTicker = (symbol: string, companyName?: string) => {
    const normalized = normalizeTickerCandidate(symbol)
    if (!normalized) return
    setPendingTicker(normalized)
    track(normalized, companyName)
    rememberTickerOrigin('command')
    go(`/ticker/${encodeURIComponent(normalized)}`)
  }

  const goToTickerAi = (symbol: string, companyName?: string) => {
    const normalized = normalizeTickerCandidate(symbol)
    if (!normalized) return
    clearPendingTicker()
    track(normalized, companyName)
    go(`/ai-analysis/${encodeURIComponent(normalized)}`)
  }

  const goToTickerScreener = (symbol: string, companyName?: string) => {
    const normalized = normalizeTickerCandidate(symbol)
    if (!normalized) return
    clearPendingTicker()
    track(normalized, companyName)
    go(`/screener?symbol=${encodeURIComponent(normalized)}`)
  }

  const openStyle = (styleName: string) => {
    const slug = slugify(styleName)
    if (!slug) return
    clearPendingTicker()
    go(`/screener/${encodeURIComponent(slug)}`)
  }

  useEffect(() => {
    openRef.current = open
  }, [open])

  const isCmdkError = useCallback((value: unknown) => {
    if (!value) return false
    const message = typeof value === 'string' ? value : String((value as any).message || '')
    const stack = typeof value === 'string' ? '' : String((value as any).stack || '')
    const combined = `${message}\n${stack}`.toLowerCase()
    return combined.includes('cmdk') && combined.includes('foreach')
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const handleError = (event: ErrorEvent) => {
      if (!openRef.current && !pendingTickerRef.current) return
      if (!isCmdkError(event.error ?? event.message)) return
      clearPendingTicker()
      setOpen(false)
      toast({ title: 'Command palette error', description: 'Please retry your search.' })
    }
    const handleRejection = (event: PromiseRejectionEvent) => {
      if (!openRef.current && !pendingTickerRef.current) return
      if (!isCmdkError(event.reason)) return
      clearPendingTicker()
      setOpen(false)
      toast({ title: 'Command palette error', description: 'Please retry your search.' })
    }
    window.addEventListener('error', handleError)
    window.addEventListener('unhandledrejection', handleRejection)
    return () => {
      window.removeEventListener('error', handleError)
      window.removeEventListener('unhandledrejection', handleRejection)
    }
  }, [clearPendingTicker, isCmdkError, toast])

  useEffect(() => {
    // Guard against mis-routes that land on /ai-analysis/:symbol after a stock-details jump.
    const pending = pendingTickerRef.current
    if (!pending) return
    const path = (pathname || '').toUpperCase()
    if (path.startsWith('/TICKER/')) {
      clearPendingTicker()
      return
    }
    if (path === `/AI-ANALYSIS/${pending}`) {
      const hash = typeof window !== 'undefined' ? window.location.hash : ''
      clearPendingTicker()
      router.replace(`/ticker/${encodeURIComponent(pending)}${hash}`)
    }
  }, [pathname, router, clearPendingTicker])

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className={cn(
          'h-9 gap-2 border-outline/10 bg-secondary/10 px-3 text-muted-foreground hover:border-outline/16 hover:bg-secondary/15 hover:text-foreground',
          className,
        )}
        onClick={() => setOpen(true)}
        aria-label={`Open ticker command bar (${shortcutHint()})`}
      >
        <SearchIcon className="h-4 w-4" aria-hidden />
        <span className="hidden md:inline">Tickers</span>
        <span className="ml-1 hidden select-none rounded-md border border-outline/10 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground md:inline">
          {shortcutHint()}
        </span>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className={cn(
            'max-w-[720px] p-0',
            'border border-outline/10 bg-card shadow-xl',
          )}
          closeClassName="right-3 top-3"
        >
          <DialogTitle className="sr-only">Ticker command bar</DialogTitle>
          <ErrorBoundary
            resetKey={open ? 'open' : 'closed'}
            onError={() => {
              toast({ title: 'Command palette error', description: 'Please retry your search.' })
            }}
            fallback={(
              <div className="space-y-3 p-4 text-sm text-muted-foreground">
                <div className="font-semibold text-foreground">Command palette ran into a problem.</div>
                <div>Close and reopen to try again.</div>
                <Button type="button" size="sm" className="h-8 rounded-full px-3 text-xs" onClick={() => setOpen(false)}>
                  Close
                </Button>
              </div>
            )}
          >
            <Command
              className="rounded-none"
              shouldFilter={true}
            >
              <CommandInput
                placeholder="Type a ticker, company, or command..."
                value={query}
                onValueChange={setQuery}
                autoFocus
              />
              <CommandList className="pb-ds-2">
                <CommandEmpty>{tickerLoading ? 'Searching...' : 'No results.'}</CommandEmpty>

                <CommandGroup heading="Actions">
                  <CommandItem
                    value="Open compare"
                    {...commandActionProps(() => {
                      close()
                      if (compare.symbols.length > 0) {
                        openCompareTray()
                        return
                      }
                      router.push(
                        buildComparePageUrl({
                          symbols: compare.symbols,
                          baseline: compare.baseline ?? (compare.symbols[0] ?? null),
                          mode: 'table',
                          deltas: compare.showDeltas,
                        }),
                        { scroll: false },
                      )
                    })}
                  >
                    <GitCompare className="h-4 w-4 text-muted-foreground" aria-hidden />
                    Open compare
                    <CommandShortcut>Enter</CommandShortcut>
                  </CommandItem>

                  <CommandItem value="Save view" {...commandActionProps(() => void saveCurrentView())}>
                    <BookmarkIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    Save this view
                  </CommandItem>

                  <CommandItem value="Copy link" {...commandActionProps(() => void copyCurrentLink())}>
                    <LinkIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    Copy link to this view
                  </CommandItem>
                </CommandGroup>

                <CommandSeparator />

                <CommandGroup heading="Jump">
                  <CommandItem value="Overview" {...commandActionProps(() => go('/overview/nowcast'))}>
                    <LayoutGridIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    Overview
                  </CommandItem>
                  <CommandItem value="Rankings" {...commandActionProps(() => go('/rankings'))}>
                    <LineChartIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    Rankings
                  </CommandItem>
                  <CommandItem value="Screener" {...commandActionProps(() => go('/screener'))}>
                    <Wand2Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    Screener
                  </CommandItem>
                  <CommandItem value="AI Feed" {...commandActionProps(() => go('/ai-analysis'))}>
                    <Wand2Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    AI Feed
                  </CommandItem>
                </CommandGroup>

                <CommandSeparator />

                {tickerCandidate ? (
                  <CommandGroup heading="Ticker">
                    <CommandItem
                      value={`Go to ${tickerCandidate}`}
                      {...commandActionProps(() => goToTicker(tickerCandidate))}
                    >
                      <span className="font-mono text-sm font-semibold">{tickerCandidate}</span>
                      <span className="text-sm text-muted-foreground">Open stock details</span>
                    </CommandItem>
                    <CommandItem
                      value={`AI ${tickerCandidate}`}
                      {...commandActionProps(() => goToTickerAi(tickerCandidate))}
                    >
                      <span className="font-mono text-sm font-semibold">{tickerCandidate}</span>
                      <span className="text-sm text-muted-foreground">Open AI memo</span>
                    </CommandItem>
                    <CommandItem
                      value={`Screener ${tickerCandidate}`}
                      {...commandActionProps(() => goToTickerScreener(tickerCandidate))}
                    >
                      <span className="font-mono text-sm font-semibold">{tickerCandidate}</span>
                      <span className="text-sm text-muted-foreground">Open setup hits</span>
                    </CommandItem>
                  </CommandGroup>
                ) : null}

                {Array.isArray(tickerResults) && tickerResults.length ? (
                  <CommandGroup heading="Matches">
                    {tickerResults.map((r) => (
                      <CommandItem
                        key={`${r.symbol}-${r.company_name || ''}`}
                        value={`${r.symbol} ${r.company_name || ''} ${r.sector || ''} ${r.overall_grade || ''}`}
                        keywords={[r.symbol, r.company_name || '', r.sector || ''].filter(Boolean)}
                        {...commandActionProps(() => goToTicker(r.symbol, r.company_name))}
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-semibold">{r.symbol}</span>
                            {r.overall_grade ? (
                              <span className="rounded-md border border-outline/10 bg-secondary/10 px-1.5 py-0.5 text-[11px] font-semibold text-muted-foreground">
                                {r.overall_grade}
                              </span>
                            ) : null}
                          </div>
                          {r.company_name ? (
                            <div className="truncate text-xs text-muted-foreground">{r.company_name}</div>
                          ) : null}
                        </div>
                        <CommandShortcut>Enter</CommandShortcut>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ) : null}

                {filteredStyles.length ? (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="Styles">
                      {filteredStyles.map((s) => (
                      <CommandItem
                        key={s.name}
                        value={`Style ${s.name}`}
                        keywords={[s.name]}
                        {...commandActionProps(() => openStyle(s.name))}
                      >
                        <Wand2Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                        <span className="min-w-0 truncate">{s.name}</span>
                        <CommandShortcut>{(s.count ?? 0).toLocaleString()}</CommandShortcut>
                      </CommandItem>
                      ))}
                    </CommandGroup>
                  </>
                ) : null}

                {recents.length ? (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="Recently viewed">
                      {recents.map((r) => (
                      <CommandItem
                        key={r.symbol}
                        value={`Recent ${r.symbol} ${r.company_name || ''}`}
                        keywords={[r.symbol, r.company_name || ''].filter(Boolean)}
                        {...commandActionProps(() => goToTicker(r.symbol, r.company_name))}
                      >
                        <span className="font-mono text-sm font-semibold">{r.symbol}</span>
                        {r.company_name ? <span className="truncate text-sm text-muted-foreground">{r.company_name}</span> : null}
                      </CommandItem>
                      ))}
                    </CommandGroup>
                  </>
                ) : null}

                {savedViews.length ? (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="Saved views">
                      {savedViews.map((v) => (
                      <CommandItem
                        key={v.id}
                        value={`Saved view ${v.name} ${v.url}`}
                        keywords={[v.name, v.url]}
                        {...commandActionProps(() => go(v.url))}
                      >
                        <BookmarkIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                        <span className="min-w-0 truncate">{v.name}</span>
                          <button
                            type="button"
                            className="ml-auto rounded-md border border-outline/10 bg-secondary/10 px-2 py-1 text-xs text-muted-foreground hover:border-outline/16 hover:text-foreground"
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              removeSavedView(v.id)
                              setSavedViews(listSavedViews())
                              toast({ title: 'Removed', description: v.name })
                            }}
                          >
                            Remove
                          </button>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </>
                ) : null}
              </CommandList>
            </Command>
          </ErrorBoundary>
        </DialogContent>
      </Dialog>
    </>
  )
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(handle)
  }, [value, delayMs])
  return debounced
}
