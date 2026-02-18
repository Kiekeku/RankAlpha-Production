'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { CopyIcon, GitCompare, LayoutGridIcon, Table2Icon, Trash2Icon, XIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/page-header'
import { PrimaryCtaButton } from '@/components/primary-cta'
import { useToast } from '@/components/ui/use-toast'
import { api } from '@/lib/api'
import { formatEasternDate } from '@/lib/date'
import { formatNumberValue } from '@/lib/format'
import { cn } from '@/lib/utils'
import { buildComparePageUrl, type ComparePageMode, normalizeCompareSymbol, useCompare } from '@/components/compare/compare_context'
import { DataStateWrapper } from '@/components/data-state-wrapper'
import { PrimaryBackLink } from '@/components/primary-back-link'
import { rememberTickerOrigin } from '@/lib/ticker_nav'
import { formatSetupHitsLabel, formatSetupTag } from '@/lib/ui_terms'
import { InlineError } from '@/components/ui/inline-error'
import { CompareTable } from '@/components/compare/CompareTable'
import { DeltaToggle } from '@/components/compare/DeltaToggle'
import { deltaLabel, setupTotals, targetUpsidePct, formatSignedPercent } from '@/components/compare/compare-utils'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { DataFreshnessBar, type DataFreshnessItem } from '@/components/data/data-freshness-bar'

const LAST_NON_COMPARE_URL_KEY = 'rankalpha.lastNonCompareUrl'
const SETUP_WINDOW_DAYS = 3
const SETUP_WINDOW_DAYS_LONG = 10

function parseSymbols(raw: string | null, max: number): string[] {
  const items = (raw || '')
    .split(',')
    .map((s) => normalizeCompareSymbol(s))
    .filter(Boolean)
  const unique: string[] = []
  const seen = new Set<string>()
  for (const sym of items) {
    if (seen.has(sym)) continue
    seen.add(sym)
    unique.push(sym)
    if (unique.length >= max) break
  }
  return unique
}

function parseMode(raw: string | null): ComparePageMode {
  const v = (raw || '').trim().toLowerCase()
  return v === 'cards' ? 'cards' : 'table'
}

function parseDeltas(raw: string | null): boolean {
  const v = (raw || '').trim().toLowerCase()
  if (!v) return true
  return v === '1' || v === 'true' || v === 'yes'
}

export function ComparePageView() {
  const compare = useCompare()
  const showRawData = SHOW_RAW_DATA
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const { toast } = useToast()
  useEffect(() => {
    try {
      const v = sessionStorage.getItem(LAST_NON_COMPARE_URL_KEY)
      if (v && (v === '/compare' || v.startsWith('/compare/'))) {
        sessionStorage.removeItem(LAST_NON_COMPARE_URL_KEY)
      }
    } catch {
      // ignore storage failures
    }
  }, [])

  const urlSymbols = useMemo(() => {
    const raw = searchParams.get('symbols') ?? searchParams.get('t') ?? searchParams.get('compare')
    return parseSymbols(raw, compare.max)
  }, [compare.max, searchParams])
  const urlBaseline = useMemo(() => {
    const base = normalizeCompareSymbol(searchParams.get('baseline') || searchParams.get('base') || '')
    return base && urlSymbols.includes(base) ? base : (urlSymbols[0] ?? null)
  }, [searchParams, urlSymbols])
  const urlDeltas = useMemo(() => parseDeltas(searchParams.get('deltas')), [searchParams])
  const urlMode = useMemo(() => parseMode(searchParams.get('mode')), [searchParams])

  const [mode, setMode] = useState<ComparePageMode>(urlMode)

  const urlHasTickersParam = searchParams.has('symbols') || searchParams.has('t') || searchParams.has('compare')
  const urlKey = useMemo(() => {
    return [
      urlHasTickersParam ? '1' : '0',
      urlSymbols.join(','),
      urlBaseline ?? '',
      urlDeltas ? '1' : '0',
      urlMode,
    ].join('|')
  }, [urlBaseline, urlDeltas, urlHasTickersParam, urlMode, urlSymbols])

  const replaceAllRef = useRef(compare.replaceAll)
  useEffect(() => {
    replaceAllRef.current = compare.replaceAll
  }, [compare.replaceAll])

  const urlChangedRef = useRef(false)
  const lastUrlKeyRef = useRef<string | null>(null)
  useEffect(() => {
    if (lastUrlKeyRef.current === null) {
      lastUrlKeyRef.current = urlKey
      return
    }
    if (lastUrlKeyRef.current === urlKey) return
    lastUrlKeyRef.current = urlKey
    urlChangedRef.current = true
  }, [urlKey])

  useEffect(() => {
    setMode(urlMode)
  }, [urlMode])

  useEffect(() => {
    if (!urlHasTickersParam) return
    replaceAllRef.current({ symbols: urlSymbols, baseline: urlBaseline, showDeltas: urlDeltas })
    urlChangedRef.current = false
  }, [urlBaseline, urlDeltas, urlHasTickersParam, urlKey, urlSymbols])

  useEffect(() => {
    if (urlHasTickersParam && urlChangedRef.current) return

    const compareBaseline = compare.baseline ?? (compare.symbols[0] ?? null)
    const href = buildComparePageUrl({
      symbols: compare.symbols,
      baseline: compareBaseline,
      mode,
      deltas: compare.showDeltas,
    })
    const current = `${pathname}${searchParams.toString() ? `?${searchParams.toString()}` : ''}`
    if (href === current) return
    router.replace(href, { scroll: false })
  }, [compare.baseline, compare.showDeltas, compare.symbols, mode, pathname, router, searchParams, urlHasTickersParam])

  const symbols = compare.symbols
  const count = symbols.length
  const baseline = compare.baseline ?? (symbols[0] ?? null)

  const { data: assets, isLoading: assetsLoading, isError: assetsError, error: assetsErrorRaw, refetch: refetchAssets } = useQuery({
    queryKey: ['compare-page-assets', symbols.join(',')],
    queryFn: async () => Promise.all(symbols.map((s) => api.getAssetDetail(s))),
    enabled: symbols.length > 0,
    staleTime: 60_000,
  })

  const { data: modelWeights } = useQuery({
    queryKey: ['grading', 'weights'],
    queryFn: () => api.getModelWeights(),
    staleTime: 300_000,
    enabled: symbols.length > 0,
  })

  const { data: setups, isLoading: setupsLoading } = useQuery({
    queryKey: ['compare-page-setups', symbols.join(','), SETUP_WINDOW_DAYS],
    queryFn: () => api.getSetupSummaries(symbols, { window_days: SETUP_WINDOW_DAYS }),
    enabled: symbols.length > 0,
    staleTime: 60_000,
  })

  const { data: setupsLong, isLoading: setupsLongLoading } = useQuery({
    queryKey: ['compare-page-setups', symbols.join(','), SETUP_WINDOW_DAYS_LONG],
    queryFn: () => api.getSetupSummaries(symbols, { window_days: SETUP_WINDOW_DAYS_LONG }),
    enabled: symbols.length > 0,
    staleTime: 60_000,
  })

  const { data: latestPrices } = useQuery({
    queryKey: ['compare-page-prices', symbols.join(',')],
    queryFn: async () => {
      const results = await Promise.all(
        symbols.map(async (sym) => {
          try {
            const res = await api.getLatestAdj({ symbol: sym })
            return res?.items?.[0] ?? null
          } catch {
            return null
          }
        }),
      )
      return results.filter(Boolean)
    },
    enabled: showRawData && symbols.length > 0,
    staleTime: 60_000,
  })

  const { data: technicals } = useQuery({
    queryKey: ['compare-page-technicals', symbols.join(',')],
    queryFn: async () => {
      const results = await Promise.all(
        symbols.map(async (sym) => {
          try {
            return await api.getTechnicalsLatest(sym)
          } catch {
            return null
          }
        }),
      )
      return results.filter(Boolean)
    },
    enabled: symbols.length > 0,
    staleTime: 60_000,
  })

  const assetBySymbol = useMemo(() => {
    const out: Record<string, any> = {}
    ;(assets ?? []).forEach((it: any) => {
      const sym = normalizeCompareSymbol(it?.symbol || '')
      if (sym) out[sym] = it
    })
    return out
  }, [assets])

  const lastUpdatedDate = useMemo(() => {
    const dates = (assets ?? [])
      .map((it: any) => it?.current_grade?.date)
      .filter((d: any) => typeof d === 'string' && d.length > 0) as string[]
    if (!dates.length) return null
    return dates.reduce((acc, d) => (new Date(d) > new Date(acc) ? d : acc), dates[0])
  }, [assets])
  const lastUpdatedLabel = useMemo(() => {
    return lastUpdatedDate ? formatEasternDate(lastUpdatedDate) : null
  }, [lastUpdatedDate])
  const statusLabel = assetsError ? 'Status: delayed' : assetsLoading ? 'Status: loading' : 'Status: live'
  const headerContextBadges = [
    lastUpdatedDate ? `As of ${formatEasternDate(lastUpdatedDate)}` : null,
    `Tickers ${count}/${compare.max}`,
    statusLabel,
  ].filter(Boolean)

  const freshnessItems = useMemo(() => {
    const summarizeDates = (dates: Array<string | null | undefined>, missingReason: string) => {
      const cleaned = dates.filter((d): d is string => typeof d === 'string' && d.length > 0)
      if (!cleaned.length) {
        return { asOf: null, status: 'missing' as const, note: null, missingReason }
      }
      const unique = Array.from(new Set(cleaned))
      const latest = cleaned.reduce((acc, d) => (new Date(d) > new Date(acc) ? d : acc), cleaned[0])
      return {
        asOf: latest,
        status: unique.length > 1 ? ('mixed' as const) : ('ok' as const),
        note: unique.length > 1 ? `Mixed (${unique.length} dates)` : null,
        missingReason: null,
      }
    }

    const scoreDates = (assets ?? []).map((it: any) => it?.current_grade?.date)
    const priceDates = (latestPrices ?? []).map((it: any) => it?.price_date)
    const technicalDates = (technicals ?? []).map((it: any) => it?.as_of_date)
    const aiDates = (assets ?? []).map((it: any) => it?.ai_analysis?.analysis_date ?? it?.ai_analysis?.as_of_date)

    const scoreMeta = summarizeDates(scoreDates, 'No scores yet')
    const priceMeta = summarizeDates(priceDates, showRawData ? 'Price unavailable' : 'Price data hidden')
    const technicalMeta = summarizeDates(technicalDates, 'No technicals yet')
    const aiMeta = summarizeDates(aiDates, 'No memo yet')

    const aiModels = (assets ?? [])
      .map((it: any) => (it?.ai_analysis?.source_name || '').trim())
      .filter(Boolean) as string[]
    const aiModelUnique = Array.from(new Set(aiModels))
    const aiModelLabel =
      aiModelUnique.length === 1
        ? `Model: ${aiModelUnique[0]}`
        : aiModelUnique.length > 1
          ? 'Model: mixed'
          : 'Model: internal'
    const aiModelNote = aiModelUnique.length > 1 ? `Mixed (${aiModelUnique.length} models)` : null

    return [
      {
        label: 'Prices',
        asOf: priceMeta.asOf,
        status: priceMeta.status,
        note: priceMeta.note,
        missingReason: priceMeta.missingReason,
      },
      {
        label: 'Scores',
        asOf: scoreMeta.asOf,
        status: scoreMeta.status,
        note: scoreMeta.note,
        version: modelWeights?.method ? `Model: ${modelWeights.method}` : 'Model: default',
        missingReason: scoreMeta.missingReason,
      },
      {
        label: 'Technicals',
        asOf: technicalMeta.asOf,
        status: technicalMeta.status,
        note: technicalMeta.note,
        missingReason: technicalMeta.missingReason,
      },
      {
        label: 'AI Memo',
        asOf: aiMeta.asOf,
        status: aiMeta.status,
        note: aiMeta.note ?? aiModelNote,
        version: aiModelLabel,
        missingReason: aiMeta.missingReason,
      },
    ] as DataFreshnessItem[]
  }, [assets, latestPrices, modelWeights, showRawData, technicals])

  const setupBySymbol = useMemo(() => {
    const out: Record<string, any> = {}
    ;(setups as any)?.items?.forEach?.((it: any) => {
      const sym = normalizeCompareSymbol(it?.symbol || it?.ticker || it?.peer_symbol || '')
      if (sym) out[sym] = it
    })
    return out
  }, [setups])

  const setupLongBySymbol = useMemo(() => {
    const out: Record<string, any> = {}
    ;(setupsLong as any)?.items?.forEach?.((it: any) => {
      const sym = normalizeCompareSymbol(it?.symbol || it?.ticker || it?.peer_symbol || '')
      if (sym) out[sym] = it
    })
    return out
  }, [setupsLong])

  const technicalsBySymbol = useMemo(() => {
    const out: Record<string, any> = {}
    ;(technicals ?? []).forEach((it: any) => {
      const sym = normalizeCompareSymbol(it?.symbol || '')
      if (sym) out[sym] = it
    })
    return out
  }, [technicals])

  const priceBySymbol = useMemo(() => {
    if (!showRawData) return {}
    const out: Record<string, number | null> = {}
    ;(latestPrices ?? []).forEach((it: any) => {
      const sym = normalizeCompareSymbol(it?.symbol || '')
      if (!sym) return
      const adj = it?.adj_close_px
      const close = it?.close_px
      const value = adj ?? close ?? null
      out[sym] = typeof value === 'number' && Number.isFinite(value) ? value : null
    })
    return out
  }, [latestPrices, showRawData])

  const priceDateBySymbol = useMemo(() => {
    const out: Record<string, string | null> = {}
    ;(latestPrices ?? []).forEach((it: any) => {
      const sym = normalizeCompareSymbol(it?.symbol || '')
      if (!sym) return
      out[sym] = it?.price_date ?? null
    })
    return out
  }, [latestPrices])

  const baselineAsset = baseline ? assetBySymbol[baseline] : null
  const interpretation = useMemo(() => {
    if (!baseline || !baselineAsset) return null
    const baselineMetrics = {
      Momentum: baselineAsset?.current_grade?.momentum_score ?? null,
      Value: baselineAsset?.current_grade?.value_score ?? null,
      Sentiment: baselineAsset?.current_grade?.sentiment_score ?? null,
    }
    const metricDeltas = Object.keys(baselineMetrics).map((key) => {
      const base = (baselineMetrics as any)[key]
      if (base == null || !Number.isFinite(Number(base))) return { key, delta: null }
      const maxDelta = symbols
        .filter((sym) => sym !== baseline)
        .map((sym) => {
          const v = assetBySymbol[sym]?.current_grade?.[`${key.toLowerCase()}_score`] ?? null
          if (v == null || !Number.isFinite(Number(v))) return null
          return Math.abs(Number(v) - Number(base))
        })
        .filter((v) => v != null) as number[]
      if (!maxDelta.length) return { key, delta: null }
      return { key, delta: Math.max(...maxDelta) }
    })
    const topDrivers = metricDeltas
      .filter((m) => m.delta != null)
      .sort((a, b) => (b.delta ?? 0) - (a.delta ?? 0))
      .slice(0, 2)
      .map((m) => m.key)

    const baselineSetup = setupBySymbol[baseline]
    const baselineSetupSummary = setupTotals(baselineSetup)
    const otherSetups = symbols
      .filter((sym) => sym !== baseline)
      .map((sym) => ({ sym, summary: setupTotals(setupBySymbol[sym]) }))
      .filter((row) => row.summary.total > 0 && row.summary.netBias !== 'neutral')
      .sort((a, b) => {
        const rank = (strength: string) => (strength === 'strong' ? 3 : strength === 'medium' ? 2 : strength === 'weak' ? 1 : 0)
        return rank(b.summary.netStrength) - rank(a.summary.netStrength)
      })
    const notableSetup = otherSetups[0]
    const setupText = notableSetup
      ? `${notableSetup.sym} has ${notableSetup.summary.netBias === 'bearish' ? 'defensive' : 'bullish'} streak (${notableSetup.summary.netStrength}). ${baseline} has ${baselineSetupSummary.total ? 'a streak' : 'none'}.`
      : baselineSetupSummary.total
        ? `${baseline} has a ${baselineSetupSummary.netBias} streak (${baselineSetupSummary.netStrength}).`
        : 'No meaningful setup streaks in the last window.'

    return {
      baseline,
      drivers: topDrivers.length ? topDrivers.join(', ') : 'No large deltas yet',
      setupText,
    }
  }, [assetBySymbol, baseline, baselineAsset, setupBySymbol, symbols])

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      toast({ title: 'Link copied', description: 'Shareable compare URL copied to clipboard.' })
    } catch {
      toast({ title: 'Copy failed', description: 'Clipboard access was blocked.' })
    }
  }

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [showScrollLeft, setShowScrollLeft] = useState(false)
  const [showScrollRight, setShowScrollRight] = useState(false)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const update = () => {
      const maxScroll = el.scrollWidth - el.clientWidth
      setShowScrollLeft(el.scrollLeft > 1)
      setShowScrollRight(maxScroll > 2 && el.scrollLeft < maxScroll - 1)
    }

    update()
    el.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      el.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [mode, count])

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader
        title="Compare"
        subtitle="Side-by-side comparison for up to 3 tickers. Updated nightly."
        contextBadges={headerContextBadges}
        primaryAction={(
          <PrimaryCtaButton onClick={handleCopyLink}>
            <CopyIcon className="h-4 w-4" aria-hidden />
            Copy link
          </PrimaryCtaButton>
        )}
        secondaryActions={[
          <PrimaryBackLink key="compare-back" kind="compare" />,
        ]}
      />
      {count ? <DataFreshnessBar items={freshnessItems} /> : null}

      <Card className="border-outline/8">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2">
              <GitCompare className="h-4 w-4" aria-hidden />
              Compare {count}/{compare.max}
            </CardTitle>
            {assetsError ? (
              <InlineError message="Couldn't load comparison data." onRetry={() => void refetchAssets()} />
            ) : (
              <div className="text-xs text-muted-foreground">
                {count ? 'Adjust baseline and deltas, then share the URL.' : 'Select tickers across the app to start comparing.'}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center rounded-full border border-outline/10 bg-card p-1" aria-label="Compare view mode">
              <button
                type="button"
                className={cn(
                  'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
                  mode === 'table' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                )}
                onClick={() => setMode('table')}
                aria-pressed={mode === 'table'}
              >
                <Table2Icon className="h-4 w-4" aria-hidden />
                <span className="hidden sm:inline">Table</span>
              </button>
              <button
                type="button"
                className={cn(
                  'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
                  mode === 'cards' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                )}
                onClick={() => setMode('cards')}
                aria-pressed={mode === 'cards'}
              >
                <LayoutGridIcon className="h-4 w-4" aria-hidden />
                <span className="hidden sm:inline">Cards</span>
              </button>
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-full px-3 text-xs"
              onClick={() => compare.clear()}
              disabled={!count}
            >
              <Trash2Icon className="mr-1 h-4 w-4" aria-hidden />
              Clear
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {count ? (
            <>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  {symbols.map((sym) => {
                    const grade = assetBySymbol[sym]?.current_grade?.overall_grade
                    const company = assetBySymbol[sym]?.company_name
                    const isBaseline = baseline === sym
                    return (
                      <Badge
                        key={sym}
                        variant="secondary"
                        className={cn(
                          'flex max-w-full items-center gap-2 py-1 pl-2 pr-1 text-xs font-semibold',
                          isBaseline && 'border border-primary/30 bg-primary/10 text-primary',
                        )}
                      >
                        <span className="tabular-nums">{sym}</span>
                        {grade ? <span className="text-[11px] text-muted-foreground">Grade {grade}</span> : null}
                        {company ? <span className="hidden max-w-[14rem] truncate text-[11px] text-muted-foreground sm:inline">{company}</span> : null}
                        <button
                          type="button"
                          className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-outline/10 bg-background/60 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                          onClick={() => compare.removeSymbol(sym)}
                          aria-label={`Remove ${sym} from compare`}
                        >
                          <span className="sr-only">Remove</span>×
                        </button>
                      </Badge>
                    )
                  })}
                </div>

                <div className="flex flex-col gap-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:gap-4">
                  <div className="space-y-1">
                    <label className="flex items-center gap-2">
                      <span className="font-semibold">Baseline (reference)</span>
                      <select
                        className="h-9 rounded-md border border-outline/10 bg-background px-2 text-sm text-foreground"
                        value={baseline ?? ''}
                        onChange={(event) => compare.setBaseline(event.target.value)}
                        aria-label="Select baseline ticker"
                      >
                        {symbols.map((sym) => (
                          <option key={sym} value={sym}>
                            {sym}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="text-[11px] text-muted-foreground">Deltas show difference vs baseline.</div>
                  </div>

                  <DeltaToggle
                    checked={compare.showDeltas}
                    onChange={(next) => compare.setShowDeltas(next)}
                    baselineLabel={baseline}
                    tooltip="Deltas compare each metric against the baseline ticker. Positive values mean higher than baseline and negative values mean lower. Use them to spot the biggest gaps quickly."
                  />
                </div>
              </div>

              {interpretation ? (
                <div className="rounded-2xl border border-outline/10 bg-secondary/10 p-3 text-xs text-muted-foreground">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-semibold text-foreground">Baseline: {interpretation.baseline}</span>
                    <span>Largest delta drivers: {interpretation.drivers}</span>
                    <span>{interpretation.setupText}</span>
                  </div>
                </div>
              ) : null}

              {assetsLoading || assetsError ? (
                <DataStateWrapper
                  status={assetsLoading ? 'loading' : 'error'}
                  context="compare"
                  loadingLabel="Loading Compare…"
                  title="Data temporarily unavailable"
                  message={assetsError ? 'Failed to load compare data.' : undefined}
                  lastUpdated={lastUpdatedLabel}
                  onRetry={assetsError ? () => void refetchAssets() : undefined}
                  error={assetsErrorRaw}
                />
              ) : mode === 'cards' ? (
                <div className="grid gap-3 lg:grid-cols-3">
                  {symbols.map((sym) => {
                    const asset = assetBySymbol[sym]
                    const setup = setupBySymbol[sym]
                    const setupLong = setupLongBySymbol[sym]
                    const grade = asset?.current_grade?.overall_grade
                    const company = asset?.company_name
                    const updated = asset?.current_grade?.date ? formatEasternDate(asset.current_grade.date) : '-'
                    const momentum = asset?.current_grade?.momentum_score ?? null
                    const value = asset?.current_grade?.value_score ?? null
                    const sentiment = asset?.current_grade?.sentiment_score ?? null
                    const scenarios = asset?.ai_analysis?.scenarios
                    const basePt = scenarios?.base?.price ?? null
                    const baseProb = scenarios?.base?.probability_pct ?? null
                    const isBaseline = baseline === sym

                    const baselineMomentum = baselineAsset?.current_grade?.momentum_score ?? null
                    const baselineValue = baselineAsset?.current_grade?.value_score ?? null
                    const baselineSentiment = baselineAsset?.current_grade?.sentiment_score ?? null
                    const baselinePt = baselineAsset?.ai_analysis?.scenarios?.base?.price ?? null
                    const baseUpside = targetUpsidePct(basePt, priceBySymbol[sym] ?? null)
                    const baselineUpside = targetUpsidePct(baselinePt, baseline ? (priceBySymbol[baseline] ?? null) : null)
                    const upsideDeltaLabel = compare.showDeltas && baseline ? deltaLabel(baseUpside, baselineUpside) : null

                    const chips = [
                      ...(Array.isArray(setup?.bullish) ? setup.bullish.slice(0, 1).map((c: any) => ({ ...c, tone: 'success' })) : []),
                      ...(Array.isArray(setup?.bearish) ? setup.bearish.slice(0, 1).map((c: any) => ({ ...c, tone: 'danger' })) : []),
                    ].filter(Boolean)
                    const longTotals = setupTotals(setupLong)

                    return (
                      <Card key={sym} className={cn('border-outline/10 bg-card', isBaseline && 'ring-2 ring-primary/30')}>
                        <CardHeader className="pb-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <div className="text-sm font-semibold">{sym}</div>
                                {grade ? (
                                  <Badge variant="secondary" className="text-[11px] font-semibold">
                                    Grade {grade}
                                  </Badge>
                                ) : null}
                              </div>
                              <div className="mt-0.5 truncate text-xs text-muted-foreground">{company || '-'}</div>
                            </div>
                            <div className="flex items-center gap-2">
                              <Link
                                href={`/ticker/${encodeURIComponent(sym)}`}
                                onClick={() => rememberTickerOrigin('compare')}
                                className="text-xs font-semibold text-primary hover:underline"
                              >
                                Open ticker
                              </Link>
                              <button
                                type="button"
                                className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-outline/10 bg-background/60 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                onClick={() => compare.removeSymbol(sym)}
                                aria-label={`Remove ${sym} from compare`}
                              >
                                <XIcon className="h-4 w-4" aria-hidden />
                              </button>
                            </div>
                          </div>
                        </CardHeader>
                        <CardContent className="space-y-3 text-sm">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span>Updated {updated}</span>
                            {isBaseline ? <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-1 font-semibold text-primary">Baseline</span> : null}
                          </div>

                          <div className="grid grid-cols-3 gap-2">
                            <div className="min-h-[64px] rounded-xl border border-outline/10 bg-secondary/10 p-2">
                              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">M</div>
                              <div className="mt-0.5 font-semibold tabular-nums text-foreground">
                                {formatNumberValue(momentum, 0)}{' '}
                                {compare.showDeltas && baseline ? (
                                  <span className="text-[11px] font-medium text-muted-foreground">({deltaLabel(momentum, baselineMomentum)})</span>
                                ) : null}
                              </div>
                            </div>
                            <div className="min-h-[64px] rounded-xl border border-outline/10 bg-secondary/10 p-2">
                              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">V</div>
                              <div className="mt-0.5 font-semibold tabular-nums text-foreground">
                                {formatNumberValue(value, 0)}{' '}
                                {compare.showDeltas && baseline ? (
                                  <span className="text-[11px] font-medium text-muted-foreground">({deltaLabel(value, baselineValue)})</span>
                                ) : null}
                              </div>
                            </div>
                            <div className="min-h-[64px] rounded-xl border border-outline/10 bg-secondary/10 p-2">
                              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">S</div>
                              <div className="mt-0.5 font-semibold tabular-nums text-foreground">
                                {formatNumberValue(sentiment, 0)}{' '}
                                {compare.showDeltas && baseline ? (
                                  <span className="text-[11px] font-medium text-muted-foreground">({deltaLabel(sentiment, baselineSentiment)})</span>
                                ) : null}
                              </div>
                            </div>
                          </div>

                          <div className="rounded-xl border border-outline/10 bg-secondary/10 p-2">
                            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Target vs price</div>
                            <div className="mt-0.5 font-semibold tabular-nums text-foreground">
                              {baseUpside == null ? '-' : formatSignedPercent(baseUpside, 1)}{' '}
                              {upsideDeltaLabel ? (
                                <span className="text-[11px] font-medium text-muted-foreground">
                                  ({upsideDeltaLabel}%)
                                </span>
                              ) : null}
                            </div>
                            <div className="mt-0.5 text-[11px] text-muted-foreground">
                              Target {basePt == null ? '-' : `$${formatNumberValue(basePt, 2)}`} · {baseProb == null ? '-' : `${formatNumberValue(baseProb, 0)}%`}
                            </div>
                          </div>

                          <div className="rounded-xl border border-outline/10 bg-secondary/10 p-2">
                            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{formatSetupHitsLabel(SETUP_WINDOW_DAYS)}</div>
                            {setupsLoading ? (
                              <div className="mt-1 text-xs text-muted-foreground">Loading…</div>
                            ) : chips.length ? (
                              <div className="mt-1 flex flex-wrap gap-2">
                                {chips.map((chip: any, idx: number) => (
                                  <Badge key={`${chip.label}-${idx}`} variant={chip.tone} className="text-[11px]">
                                    {formatSetupTag(chip.label, chip.streak_days)}
                                  </Badge>
                                ))}
                              </div>
                            ) : (
                              <div className="mt-1 text-xs text-muted-foreground">-</div>
                            )}
                            <div className="mt-1 text-[11px] text-muted-foreground">
                              {formatSetupHitsLabel(SETUP_WINDOW_DAYS_LONG)}:{' '}
                              {setupsLongLoading ? 'Loading…' : longTotals.total ? `${longTotals.total} hits` : '-'}
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    )
                  })}
                </div>
              ) : (
                <div className="relative">
                  {showScrollLeft ? (
                    <div className="pointer-events-none absolute inset-y-0 left-0 z-20 w-10 bg-gradient-to-r from-card to-transparent" aria-hidden />
                  ) : null}
                  {showScrollRight ? (
                    <div className="pointer-events-none absolute inset-y-0 right-0 z-20 w-10 bg-gradient-to-l from-card to-transparent" aria-hidden />
                  ) : null}

                  <div
                    ref={scrollRef}
                    className="overflow-x-auto rounded-2xl border border-outline/10 bg-card"
                  >
                    <CompareTable
                      symbols={symbols}
                      baseline={baseline}
                      showDeltas={compare.showDeltas}
                      assetBySymbol={assetBySymbol}
                      technicalsBySymbol={technicalsBySymbol}
                      priceBySymbol={priceBySymbol}
                      priceDateBySymbol={priceDateBySymbol}
                      setupBySymbol={setupBySymbol}
                      setupLongBySymbol={setupLongBySymbol}
                      setupsLoading={setupsLoading}
                      setupsLongLoading={setupsLongLoading}
                      shortWindowDays={SETUP_WINDOW_DAYS}
                      longWindowDays={SETUP_WINDOW_DAYS_LONG}
                    />
                  </div>
                </div>
              )}
            </>
          ) : (
            <DataStateWrapper
              status="empty"
              context="compare"
              title="No tickers selected"
              message="Add tickers to Compare from Rankings, Screener, or AI Feed."
              tips={[
                'Step 1: Use the compare checkbox on any rankings or screener row.',
                'Step 2: Open the tray once a ticker is selected.',
                'Step 3: Click Open Compare to view side-by-side deltas.',
              ]}
              actions={[
                { label: 'Go to Rankings', onClick: () => router.push('/rankings'), variant: 'default' },
                { label: 'Try Screener', onClick: () => router.push('/screener'), variant: 'outline' },
                { label: 'Try AI Feed', onClick: () => router.push('/ai-analysis'), variant: 'outline' },
              ]}
            />
          )}
        </CardContent>
      </Card>

      <div className="text-xs text-muted-foreground">
        Tip: Use checkboxes to add tickers to Compare. The compare set persists via local storage.
      </div>
    </div>
  )
}
