'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { api, AiAnalysisItem } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { ClickableCard } from '@/components/interaction/clickable_card'
import { DataStateWrapper } from '@/components/data-state-wrapper'
import { PageHeader } from '@/components/page-header'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { formatEasternDate } from '@/lib/date'
import { AlertTriangle, ChevronDownIcon, CopyIcon, FilterIcon, XIcon } from 'lucide-react'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { AiAnalysisTabs } from '@/components/ai-analysis/ai_analysis_tabs'
import { MultiSelect } from '@/components/filters/multi-select'
import { SavedViewsDialog } from '@/components/saved-views/saved_views_dialog'
import { SavedViewsButton } from '@/components/saved-views/saved_views_button'
import { useSavedViewsDrawer, useSavedViewsLinks } from '@/components/saved-views/use_saved_views_drawer'
import { useShareCurrentView } from '@/components/saved-views/use_share_current_view'
import { useLoadSavedView } from '@/components/saved-views/use_load_saved_view'
import { readLocalStorageJson, readSessionStorageItem, removeSessionStorageItem, writeLocalStorageJson, writeSessionStorageItem } from '@/lib/storage'
import { CompareCheckbox } from '@/components/compare/compare_checkbox'
import { cn } from '@/lib/utils'
import { TooltipCopy } from '@/components/tooltip_copy'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Button } from '@/components/ui/button'
import { useCountDeltaBadge } from '@/lib/use_count_delta'
import { rememberTickerOrigin } from '@/lib/ticker_nav'
import { InlineError } from '@/components/ui/inline-error'
import { ActiveFilterChips } from '@/components/filters/ActiveFilterChips'
import { FilterGroup, FilterSidebar } from '@/components/filters/FilterSidebar'
import { useFilterRailState } from '@/components/filters/use_filter_rail_state'
import { computeHumanTargetBucket } from '@/lib/human_targets'
import {
  fmtBullBearSpread,
  fmtPriceTarget,
  fmtProbability,
  getHumanTargetBucketMeta,
} from '@/lib/ai_analysis_format'

type AiAnalysisPersistedFilters = {
  sortChoice?: 'date_desc' | 'date_asc' | 'symbol_asc' | 'symbol_desc'
}

const AI_ANALYSIS_FILTERS_STORAGE_KEY = 'rankalpha.ai_analysis.filters.v1'
const AI_ANALYSIS_SAVED_VIEWS_KEY = 'rankalpha.ai_analysis.saved_views.v1'
const AI_ANALYSIS_FEED_SCROLL_Y_KEY = 'rankalpha.ai_analysis.feedScrollY'
const AI_ANALYSIS_FILTERS_COLLAPSED_KEY = 'rankalpha.aiAnalysis.filtersCollapsed.v1'

type SearchParamsLike = { get: (key: string) => string | null }

function parseAiSortChoice(searchParams: SearchParamsLike): AiAnalysisPersistedFilters['sortChoice'] | null {
  const sortBy = (searchParams.get('sort_by') || '').trim().toLowerCase()
  const sortOrder = (searchParams.get('sort_order') || '').trim().toLowerCase()
  if (!sortBy || !sortOrder) return null
  if (sortBy === 'date' && (sortOrder === 'asc' || sortOrder === 'desc')) return sortOrder === 'asc' ? 'date_asc' : 'date_desc'
  if (sortBy === 'symbol' && (sortOrder === 'asc' || sortOrder === 'desc')) return sortOrder === 'asc' ? 'symbol_asc' : 'symbol_desc'
  return null
}

function parsePage(raw: string | null): number {
  const n = Number(raw)
  if (!Number.isFinite(n)) return 1
  const i = Math.floor(n)
  return i >= 1 ? i : 1
}

function normalizeStringList(values: string[], { lower = false }: { lower?: boolean } = {}): string[] {
  const out: string[] = []
  for (const v of values) {
    const s = (v || '').trim()
    if (!s) continue
    out.push(lower ? s.toLowerCase() : s)
  }
  return Array.from(new Set(out))
}

function parseFiniteNumber(raw: string | null): number | undefined {
  if (!raw) return undefined
  const n = Number(raw)
  return Number.isFinite(n) ? n : undefined
}

function easternIsoDaysAgo(daysAgo: number): string {
  const DAY_MS = 24 * 60 * 60 * 1000
  return formatEasternDate(new Date(Date.now() - daysAgo * DAY_MS))
}

export default function AiAnalysisPage() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [symbolInput, setSymbolInput] = useState('')
  const [sortChoice, setSortChoice] = useState<NonNullable<AiAnalysisPersistedFilters['sortChoice']>>('date_desc')
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const { collapsed: filtersCollapsed, setCollapsed: setFiltersCollapsed } = useFilterRailState(
    AI_ANALYSIS_FILTERS_COLLAPSED_KEY,
  )
  const hasInitializedRef = useRef(false)
  const didInitRef = useRef(false)
  const symbolDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const resultsTopRef = useRef<HTMLDivElement | null>(null)
  const skipAutoScrollRef = useRef(false)
  const pageSize = 20
  const page = useMemo(() => parsePage(searchParams.get('page')), [searchParams])
  const symbol = useMemo(() => (searchParams.get('symbol') || '').trim().toUpperCase(), [searchParams])
  const dateFrom = useMemo(() => (searchParams.get('date_from') || '').trim(), [searchParams])
  const dateTo = useMemo(() => (searchParams.get('date_to') || '').trim(), [searchParams])
  const ratings = useMemo(() => normalizeStringList(searchParams.getAll('ratings'), { lower: true }), [searchParams])
  const confidences = useMemo(() => normalizeStringList(searchParams.getAll('confidences'), { lower: true }), [searchParams])
  const sectors = useMemo(() => normalizeStringList(searchParams.getAll('sectors')), [searchParams])
  const nearestScenarios = useMemo(() => normalizeStringList(searchParams.getAll('nearest_scenarios'), { lower: true }), [searchParams])
  const { viewsOpen, openViews, onOpenChange } = useSavedViewsDrawer({
    pathname,
    fallbackPath: '/ai-analysis',
    searchParams,
    router,
  })

  const nearestDistanceMaxRaw = useMemo(() => (searchParams.get('nearest_distance_pct_max') || '').trim(), [searchParams])
  const deltaBaseMinRaw = useMemo(() => (searchParams.get('delta_base_pct_min') || '').trim(), [searchParams])
  const deltaBaseMaxRaw = useMemo(() => (searchParams.get('delta_base_pct_max') || '').trim(), [searchParams])
  const baseProbMinRaw = useMemo(() => (searchParams.get('base_probability_pct_min') || '').trim(), [searchParams])
  const resultsScrollKey = useMemo(() => {
    return [
      symbol,
      dateFrom,
      dateTo,
      ratings.join(','),
      confidences.join(','),
      sectors.join(','),
      nearestScenarios.join(','),
      nearestDistanceMaxRaw,
      deltaBaseMinRaw,
      deltaBaseMaxRaw,
      baseProbMinRaw,
      sortChoice,
    ].join('|')
  }, [
    symbol,
    dateFrom,
    dateTo,
    ratings,
    confidences,
    sectors,
    nearestScenarios,
    nearestDistanceMaxRaw,
    deltaBaseMinRaw,
    deltaBaseMaxRaw,
    baseProbMinRaw,
    sortChoice,
  ])

  const nearestDistanceMax = useMemo(() => parseFiniteNumber(nearestDistanceMaxRaw), [nearestDistanceMaxRaw])
  const deltaBaseMin = useMemo(() => parseFiniteNumber(deltaBaseMinRaw), [deltaBaseMinRaw])
  const deltaBaseMax = useMemo(() => parseFiniteNumber(deltaBaseMaxRaw), [deltaBaseMaxRaw])
  const baseProbMin = useMemo(() => parseFiniteNumber(baseProbMinRaw), [baseProbMinRaw])
  const sortChoiceFromUrl = useMemo(() => parseAiSortChoice(searchParams), [searchParams])
  const effectiveSortChoice = sortChoiceFromUrl ?? sortChoice
  const sortLabel =
    effectiveSortChoice === 'date_desc'
      ? 'Date (Newest First)'
      : effectiveSortChoice === 'date_asc'
        ? 'Date (Oldest First)'
        : effectiveSortChoice === 'symbol_asc'
          ? 'Symbol (A–Z)'
          : 'Symbol (Z–A)'
  const aiSortBy = effectiveSortChoice.startsWith('symbol') ? 'symbol' : 'date'
  const aiSortOrder = effectiveSortChoice.endsWith('asc') ? 'asc' : 'desc'

  const { data, isLoading, isError, error: analysisErrorRaw, refetch } = useQuery({
    queryKey: [
      'ai-analysis-latest',
      symbol,
      dateFrom,
      dateTo,
      ratings.join(','),
      confidences.join(','),
      sectors.join(','),
      nearestScenarios.join(','),
      nearestDistanceMaxRaw,
      deltaBaseMinRaw,
      deltaBaseMaxRaw,
      baseProbMinRaw,
      page,
      effectiveSortChoice,
    ],
    queryFn: () => api.listAiAnalysesLatest({
      symbol: symbol || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      ratings: ratings.length ? ratings : undefined,
      confidences: confidences.length ? confidences : undefined,
      sectors: sectors.length ? sectors : undefined,
      nearest_scenarios: nearestScenarios.length ? nearestScenarios : undefined,
      nearest_distance_pct_max: nearestDistanceMax,
      delta_base_pct_min: deltaBaseMin,
      delta_base_pct_max: deltaBaseMax,
      base_probability_pct_min: baseProbMin,
      skip: (page - 1) * pageSize,
      limit: pageSize,
      sort_by: effectiveSortChoice.startsWith('symbol') ? 'symbol' : 'date',
      sort_order: effectiveSortChoice.endsWith('asc') ? 'asc' : 'desc',
      include_proximity: true,
    }),
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
  })

  const { data: sectorsData } = useQuery({
    queryKey: ['ai-analysis-sectors'],
    queryFn: () => api.listSectors(),
    staleTime: 10 * 60 * 1000,
  })

  const items = useMemo(() => data?.items ?? [], [data?.items])
  const latestAsOf = useMemo(() => {
    if (!items.length) return null
    return items.reduce((acc, it) => (acc > it.as_of_date ? acc : it.as_of_date), items[0].as_of_date)
  }, [items])
  const lastUpdatedLabel = useMemo(() => {
    return latestAsOf ? formatEasternDate(latestAsOf) : null
  }, [latestAsOf])
  const total = data?.total_count || 0
  const statusLabel = isError ? 'Status: delayed' : isLoading ? 'Status: loading' : 'Status: live'
  const headerContextBadges = [
    latestAsOf ? `As of ${formatEasternDate(latestAsOf)}` : null,
    total ? `Universe ${total.toLocaleString()}` : null,
    statusLabel,
  ].filter(Boolean)
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const sortChipLabel =
    effectiveSortChoice === 'date_desc'
      ? 'Sort: Date (Newest)'
      : effectiveSortChoice === 'date_asc'
        ? 'Sort: Date (Oldest)'
        : effectiveSortChoice === 'symbol_asc'
          ? 'Sort: Symbol (A–Z)'
          : 'Sort: Symbol (Z–A)'

  const replaceAiUrl = useCallback((next: Partial<{
    symbol: string
    page: number
    sortChoice: NonNullable<AiAnalysisPersistedFilters['sortChoice']>
    date_from: string
    date_to: string
    ratings: string[]
    confidences: string[]
    sectors: string[]
    nearest_scenarios: string[]
    nearest_distance_pct_max: string
    delta_base_pct_min: string
    delta_base_pct_max: string
    base_probability_pct_min: string
  }>) => {
    const basePath = pathname || '/ai-analysis'
    const params = new URLSearchParams(searchParams.toString())

    const setOptionalString = (key: string, value: string) => {
      const trimmed = (value || '').trim()
      if (trimmed) params.set(key, trimmed)
      else params.delete(key)
    }

    const setRepeatable = (key: string, values: string[]) => {
      params.delete(key)
      values.forEach((v) => {
        const s = (v || '').trim()
        if (!s) return
        params.append(key, s)
      })
    }

    if (Object.prototype.hasOwnProperty.call(next, 'symbol')) {
      const nextSymbol = (next.symbol || '').trim()
      if (nextSymbol) params.set('symbol', nextSymbol.toUpperCase())
      else params.delete('symbol')
    }

    if (Object.prototype.hasOwnProperty.call(next, 'page')) {
      const nextPage = next.page ?? 1
      if (nextPage > 1) params.set('page', String(nextPage))
      else params.delete('page')
    }

    const hasSortChoice = Object.prototype.hasOwnProperty.call(next, 'sortChoice')
    const nextSort = (hasSortChoice && next.sortChoice ? next.sortChoice : effectiveSortChoice)
    const nextSortBy = nextSort.startsWith('symbol') ? 'symbol' : 'date'
    const nextSortOrder = nextSort.endsWith('asc') ? 'asc' : 'desc'
    params.set('sort_by', nextSortBy)
    params.set('sort_order', nextSortOrder)

    if (Object.prototype.hasOwnProperty.call(next, 'date_from')) setOptionalString('date_from', next.date_from ?? '')
    if (Object.prototype.hasOwnProperty.call(next, 'date_to')) setOptionalString('date_to', next.date_to ?? '')
    if (Object.prototype.hasOwnProperty.call(next, 'nearest_distance_pct_max')) setOptionalString('nearest_distance_pct_max', next.nearest_distance_pct_max ?? '')
    if (Object.prototype.hasOwnProperty.call(next, 'delta_base_pct_min')) setOptionalString('delta_base_pct_min', next.delta_base_pct_min ?? '')
    if (Object.prototype.hasOwnProperty.call(next, 'delta_base_pct_max')) setOptionalString('delta_base_pct_max', next.delta_base_pct_max ?? '')
    if (Object.prototype.hasOwnProperty.call(next, 'base_probability_pct_min')) setOptionalString('base_probability_pct_min', next.base_probability_pct_min ?? '')
    if (Object.prototype.hasOwnProperty.call(next, 'ratings')) setRepeatable('ratings', next.ratings ?? [])
    if (Object.prototype.hasOwnProperty.call(next, 'confidences')) setRepeatable('confidences', next.confidences ?? [])
    if (Object.prototype.hasOwnProperty.call(next, 'sectors')) setRepeatable('sectors', next.sectors ?? [])
    if (Object.prototype.hasOwnProperty.call(next, 'nearest_scenarios')) setRepeatable('nearest_scenarios', next.nearest_scenarios ?? [])

    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    const currentUrl = searchParams.toString() ? `${basePath}?${searchParams.toString()}` : basePath
    if (nextUrl === currentUrl) return
    router.replace(nextUrl, { scroll: false })
  }, [effectiveSortChoice, pathname, router, searchParams])

  const applySymbolSearch = useCallback((raw: string) => {
    const next = (raw || '').trim().toUpperCase()
    if (!symbol && next && typeof window !== 'undefined') {
      writeSessionStorageItem(AI_ANALYSIS_FEED_SCROLL_Y_KEY, String(window.scrollY || 0))
    }
    replaceAiUrl({ symbol: next, page: 1 })
  }, [replaceAiUrl, symbol])

  const clearSymbolSearch = useCallback(() => {
    const raw = readSessionStorageItem(AI_ANALYSIS_FEED_SCROLL_Y_KEY)
    const y = raw ? Number(raw) : null
    if (typeof window !== 'undefined' && y != null && Number.isFinite(y)) {
      skipAutoScrollRef.current = true
    }
    setSymbolInput('')
    replaceAiUrl({ symbol: '', page: 1 })

    removeSessionStorageItem(AI_ANALYSIS_FEED_SCROLL_Y_KEY)
    if (typeof window !== 'undefined' && y != null && Number.isFinite(y)) {
      window.setTimeout(() => {
        try {
          window.scrollTo(0, y)
        } catch {
          // ignore
        }
      }, 60)
    }
  }, [replaceAiUrl])
  const activeFilterChips = useMemo(() => {
    const chips: Array<{ key: string; label: string; onRemove?: () => void }> = []
    if (symbol) chips.push({ key: 'symbol', label: `Symbol: ${symbol}`, onRemove: clearSymbolSearch })
    if (dateFrom) chips.push({ key: 'date_from', label: `From: ${dateFrom}`, onRemove: () => replaceAiUrl({ date_from: '', page: 1 }) })
    if (dateTo) chips.push({ key: 'date_to', label: `To: ${dateTo}`, onRemove: () => replaceAiUrl({ date_to: '', page: 1 }) })
    if (ratings.length) chips.push({ key: 'ratings', label: `Rating (${ratings.length})`, onRemove: () => replaceAiUrl({ ratings: [], page: 1 }) })
    if (confidences.length) chips.push({ key: 'confidences', label: `Model confidence (${confidences.length})`, onRemove: () => replaceAiUrl({ confidences: [], page: 1 }) })
    if (sectors.length) chips.push({ key: 'sectors', label: `Sector (${sectors.length})`, onRemove: () => replaceAiUrl({ sectors: [], page: 1 }) })
    if (nearestScenarios.length) chips.push({ key: 'scenarios', label: `Scenario (${nearestScenarios.length})`, onRemove: () => replaceAiUrl({ nearest_scenarios: [], page: 1 }) })
    if (nearestDistanceMaxRaw) chips.push({ key: 'distance', label: `Distance <= ${nearestDistanceMaxRaw}%`, onRemove: () => replaceAiUrl({ nearest_distance_pct_max: '', page: 1 }) })
    if (deltaBaseMinRaw) chips.push({ key: 'delta_base_min', label: `Delta base >= ${deltaBaseMinRaw}%`, onRemove: () => replaceAiUrl({ delta_base_pct_min: '', page: 1 }) })
    if (deltaBaseMaxRaw) chips.push({ key: 'delta_base_max', label: `Delta base <= ${deltaBaseMaxRaw}%`, onRemove: () => replaceAiUrl({ delta_base_pct_max: '', page: 1 }) })
    if (baseProbMinRaw) chips.push({ key: 'base_prob', label: `Base prob >= ${baseProbMinRaw}%`, onRemove: () => replaceAiUrl({ base_probability_pct_min: '', page: 1 }) })
    chips.push({
      key: 'sort',
      label: sortChipLabel,
      onRemove: () => {
        setSortChoice('date_desc')
        replaceAiUrl({ sortChoice: 'date_desc', page: 1 })
      },
    })
    return chips
  }, [baseProbMinRaw, clearSymbolSearch, confidences.length, dateFrom, dateTo, deltaBaseMaxRaw, deltaBaseMinRaw, nearestDistanceMaxRaw, nearestScenarios.length, ratings.length, replaceAiUrl, sectors.length, sortChipLabel, symbol])
  const rangeStart = total ? (page - 1) * pageSize + 1 : 0
  const rangeEnd = total ? Math.min(page * pageSize, total) : 0
  const filterKey = useMemo(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('page')
    return params.toString()
  }, [searchParams])
  const { delta: countDelta } = useCountDeltaBadge(total, filterKey)



  const { currentSavedViewQuery, savedViewsBasePath, buildSavedViewUrlForQuery } = useSavedViewsLinks({
    pathname,
    fallbackPath: '/ai-analysis',
    searchParams,
  })

  const loadSavedView = useLoadSavedView({
    basePath: savedViewsBasePath,
    router,
  })

  const resetAllFilters = useCallback(() => {
    setSymbolInput('')
    setSortChoice('date_desc')
    replaceAiUrl({
      symbol: '',
      page: 1,
      sortChoice: 'date_desc',
      date_from: '',
      date_to: '',
      ratings: [],
      confidences: [],
      sectors: [],
      nearest_scenarios: [],
      nearest_distance_pct_max: '',
      delta_base_pct_min: '',
      delta_base_pct_max: '',
      base_probability_pct_min: '',
    })

    const raw = readSessionStorageItem(AI_ANALYSIS_FEED_SCROLL_Y_KEY)
    removeSessionStorageItem(AI_ANALYSIS_FEED_SCROLL_Y_KEY)
    const y = raw ? Number(raw) : null
    if (typeof window !== 'undefined' && y != null && Number.isFinite(y)) {
      window.setTimeout(() => {
        try {
          window.scrollTo(0, y)
        } catch {
          // ignore
        }
      }, 60)
    }
  }, [replaceAiUrl, setSortChoice, setSymbolInput])

  const applyAiPreset = useCallback((preset: 'high_confidence' | 'recent_bullish' | 'near_base') => {
    resetAllFilters()
    if (preset === 'high_confidence') {
      replaceAiUrl({ confidences: ['high'], page: 1 })
      return
    }
    if (preset === 'recent_bullish') {
      replaceAiUrl({
        ratings: ['strong_buy', 'buy'],
        date_from: easternIsoDaysAgo(30),
        page: 1,
      })
      return
    }
    replaceAiUrl({
      nearest_scenarios: ['base'],
      nearest_distance_pct_max: '5',
      page: 1,
    })
  }, [replaceAiUrl, resetAllFilters])

  const aiPresets = [
    {
      key: 'high-confidence',
      label: 'High confidence only',
      description: 'Model confidence set to High.',
      onApply: () => applyAiPreset('high_confidence'),
    },
    {
      key: 'recent-bullish',
      label: 'Recent bullish',
      description: 'Strong Buy/Buy in the last 30 days.',
      onApply: () => applyAiPreset('recent_bullish'),
    },
    {
      key: 'near-base',
      label: 'Near base (≤5%)',
      description: 'Nearest scenario base within 5%.',
      onApply: () => applyAiPreset('near_base'),
    },
  ]

  const shareCurrentView = useShareCurrentView({
    failureDescription: 'Your browser blocked clipboard access.',
  })

  useEffect(() => {
    if (didInitRef.current) return
    didInitRef.current = true
    setSymbolInput(symbol)

    const persisted = readLocalStorageJson<AiAnalysisPersistedFilters>(AI_ANALYSIS_FILTERS_STORAGE_KEY)
    const persistedSort =
      persisted?.sortChoice && ['date_desc', 'date_asc', 'symbol_asc', 'symbol_desc'].includes(persisted.sortChoice)
        ? persisted.sortChoice
        : null

    if (sortChoiceFromUrl) {
      setSortChoice(sortChoiceFromUrl)
    } else if (persistedSort) {
      setSortChoice(persistedSort)
      replaceAiUrl({ sortChoice: persistedSort, page: 1 })
    }

    hasInitializedRef.current = true
  }, [replaceAiUrl, sortChoiceFromUrl, symbol])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    writeLocalStorageJson(AI_ANALYSIS_FILTERS_STORAGE_KEY, {
      sortChoice,
    } satisfies AiAnalysisPersistedFilters)
  }, [sortChoice])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    setSymbolInput(symbol)
  }, [symbol])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    if (!sortChoiceFromUrl) return
    if (sortChoiceFromUrl === sortChoice) return
    setSortChoice(sortChoiceFromUrl)
  }, [sortChoice, sortChoiceFromUrl])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    if (typeof window === 'undefined') return
    if (skipAutoScrollRef.current) {
      skipAutoScrollRef.current = false
      return
    }
    const el = resultsTopRef.current
    if (!el) {
      window.scrollTo({ top: 0, left: 0 })
      return
    }
    const rect = el.getBoundingClientRect()
    if (rect.top < 0 || rect.top > window.innerHeight) {
      el.scrollIntoView({ block: 'start' })
    }
  }, [resultsScrollKey])

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader
        title="AI Feed"
        subtitle="Latest AI memos across screened companies. Updated bi-weekly / post-earnings."
        contextBadges={headerContextBadges}
        titleAddon={(
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex items-center gap-1 rounded-full border border-status-warning/30 bg-status-warning/10 px-2.5 py-1 text-[11px] font-semibold text-status-warning-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                  Experimental
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs px-3 py-2 text-xs leading-relaxed">
                Experimental: model outputs may change and should be verified.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
        primaryAction={<PrimaryCtaLink href="/rankings">Go to Rankings</PrimaryCtaLink>}
        secondaryActions={[
          (
            <Link
              key="ai-methodology"
              href="/about/ai-analysis"
              className="inline-flex h-8 items-center gap-2 rounded-full px-2 text-xs font-semibold text-muted-foreground transition hover:bg-secondary/40 hover:text-foreground"
            >
              AI Methodology
            </Link>
          ),
          <SavedViewsButton key="ai-saved" onClick={openViews} />,
          (
            <TooltipCopy key="ai-copy" tooltipKey="global.share">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 rounded-full px-2 text-xs font-semibold text-muted-foreground hover:bg-secondary/40 hover:text-foreground"
                onClick={shareCurrentView}
              >
                <CopyIcon className="mr-1 h-3.5 w-3.5" aria-hidden />
                Copy link
              </Button>
            </TooltipCopy>
          ),
        ]}
        tabs={<AiAnalysisTabs />}
        activeChips={(
          <div className="rounded-2xl border border-outline/12 bg-background/90 p-3 shadow-sm backdrop-blur">
            <ActiveFilterChips
              chips={activeFilterChips}
              onClearAll={resetAllFilters}
              clearLabel="Reset filters"
            />
            {filtersCollapsed ? (
              <div className="mt-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="hidden h-8 rounded-full px-3 text-[11px] lg:inline-flex"
                  onClick={() => setFiltersCollapsed(false)}
                >
                  Show filters
                </Button>
              </div>
            ) : null}
            {aiPresets.length ? (
              <div className="mt-3 space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Filter presets</div>
                <div className="flex flex-wrap gap-2">
                  {aiPresets.map((preset) => (
                    <button
                      key={preset.key}
                      type="button"
                      onClick={preset.onApply}
                      title={preset.description}
                      className="rounded-full border border-outline/10 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:border-outline/20 hover:text-foreground"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="mt-2">
              <SavedViewsDialog
                open={viewsOpen}
                onOpenChange={onOpenChange}
                storageKey={AI_ANALYSIS_SAVED_VIEWS_KEY}
                currentQuery={currentSavedViewQuery}
                buildUrlForQuery={buildSavedViewUrlForQuery}
                onLoad={loadSavedView}
                namePlaceholder="e.g., Recent semiconductor updates"
                showQueryPreview={false}
                showSavedAt
              />
            </div>
          </div>
        )}
      />

      <div
        className={cn(
          'lg:grid lg:items-start lg:gap-6',
          filtersCollapsed ? 'lg:grid-cols-1' : 'lg:grid-cols-[minmax(0,320px),1fr]',
        )}
      >
        <aside className={cn('space-y-4 lg:sticky lg:top-24 lg:self-start', filtersCollapsed && 'lg:hidden')}>
          <Card className="border-outline/8">
            <CardHeader className="relative gap-1 pb-2">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="flex items-center gap-2 text-lg">
                  <FilterIcon className="h-4 w-4" />
                  Filters
                </CardTitle>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground lg:hidden"
                    onClick={() => setMobileFiltersOpen((prev) => !prev)}
                    aria-expanded={mobileFiltersOpen}
                    aria-controls="ai-analysis-filters"
                  >
                    {mobileFiltersOpen ? 'Hide' : 'Show'}
                    <ChevronDownIcon className={`h-4 w-4 transition-transform ${mobileFiltersOpen ? 'rotate-180' : ''}`} />
                  </button>
                  <button
                    type="button"
                    className="hidden items-center gap-1 rounded-full border border-outline/10 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground lg:inline-flex"
                    onClick={() => setFiltersCollapsed(true)}
                    aria-label="Collapse filters"
                  >
                    Collapse
                  </button>
                </div>
              </div>
              <CardDescription className="text-xs text-muted-foreground">
                Search the analyzed universe.
              </CardDescription>
            </CardHeader>
            <CardContent className="relative flex flex-col gap-3">
              <div className={cn('space-y-1.5', 'lg:hidden', mobileFiltersOpen ? 'hidden' : 'block')}>
                <label htmlFor="aiSymbolMobile" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Search
                </label>
                <div className="relative">
                  <input
                    id="aiSymbolMobile"
                    type="search"
                    placeholder="Symbol"
                    value={symbolInput}
                    onChange={(e) => {
                      const next = e.target.value.toUpperCase()
                      setSymbolInput(next)
                      if (symbolDebounceRef.current) clearTimeout(symbolDebounceRef.current)
                      symbolDebounceRef.current = setTimeout(() => {
                        applySymbolSearch(next)
                      }, 300)
                    }}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter') return
                      e.preventDefault()
                      if (symbolDebounceRef.current) clearTimeout(symbolDebounceRef.current)
                      applySymbolSearch(e.currentTarget.value)
                    }}
                    className={cn(
                      'h-9 w-full rounded-md border bg-background px-3 pr-9 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring',
                    )}
                    autoComplete="off"
                  />
                  {symbolInput.trim() ? (
                    <button
                      type="button"
                      className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex h-7 w-7 items-center justify-center rounded-full border border-outline/10 bg-background/60 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={clearSymbolSearch}
                      aria-label="Clear ticker search"
                    >
                      <XIcon className="h-4 w-4" aria-hidden />
                    </button>
                  ) : null}
                </div>
              </div>

              <div
                id="ai-analysis-filters"
                className={cn('space-y-4', mobileFiltersOpen ? 'block' : 'hidden', 'lg:block')}
              >
                <FilterSidebar>
                  <div className="space-y-3">
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="aiSymbol" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Search
                      </label>
                      <div className="relative">
                        <input
                          id="aiSymbol"
                          type="search"
                          placeholder="Symbol"
                          value={symbolInput}
                          onChange={(e) => {
                            const next = e.target.value.toUpperCase()
                            setSymbolInput(next)
                            if (symbolDebounceRef.current) clearTimeout(symbolDebounceRef.current)
                            symbolDebounceRef.current = setTimeout(() => {
                              applySymbolSearch(next)
                            }, 300)
                          }}
                          onKeyDown={(e) => {
                            if (e.key !== 'Enter') return
                            e.preventDefault()
                            if (symbolDebounceRef.current) clearTimeout(symbolDebounceRef.current)
                            applySymbolSearch(e.currentTarget.value)
                          }}
                          className="h-9 w-full rounded-md border bg-background px-3 pr-9 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                          autoComplete="off"
                        />
                        {symbolInput.trim() ? (
                          <button
                            type="button"
                            className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex h-7 w-7 items-center justify-center rounded-full border border-outline/10 bg-background/60 text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={clearSymbolSearch}
                            aria-label="Clear ticker search"
                          >
                            <XIcon className="h-4 w-4" aria-hidden />
                          </button>
                        ) : null}
                      </div>
                      <div className="text-[11px] text-muted-foreground">Enter a ticker (e.g., NVDA). Leave blank for all.</div>
                    </div>
                  </div>

                  <FilterGroup title="Recency">
                    <div className="space-y-1.5">
                      <div className="flex flex-wrap gap-2">
                        {[{ label: '7d', days: 7 }, { label: '30d', days: 30 }, { label: '90d', days: 90 }].map((p) => (
                          <button
                            key={p.label}
                            type="button"
                            className="rounded-full border border-outline/10 bg-card px-3 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                            onClick={() => replaceAiUrl({ date_from: easternIsoDaysAgo(p.days), page: 1 })}
                          >
                            Last {p.label}
                          </button>
                        ))}
                        <button
                          type="button"
                          className="rounded-full border border-outline/10 bg-card px-3 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                          onClick={() => replaceAiUrl({ date_from: '', date_to: '', page: 1 })}
                        >
                          All time
                        </button>
                      </div>
                    </div>
                  </FilterGroup>

                  <FilterGroup title="Date range">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <label htmlFor="aiDateFrom" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          From
                        </label>
                        <input
                          id="aiDateFrom"
                          type="date"
                          value={dateFrom}
                          onChange={(e) => replaceAiUrl({ date_from: e.currentTarget.value, page: 1 })}
                          className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label htmlFor="aiDateTo" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          To
                        </label>
                        <input
                          id="aiDateTo"
                          type="date"
                          value={dateTo}
                          onChange={(e) => replaceAiUrl({ date_to: e.currentTarget.value, page: 1 })}
                          className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                    </div>
                  </FilterGroup>

                  <FilterGroup title="Rating">
                    <MultiSelect
                      label="Rating"
                      hideLabel
                      options={[
                        { name: 'strong_buy', count: 0 },
                        { name: 'buy', count: 0 },
                        { name: 'neutral', count: 0 },
                        { name: 'sell', count: 0 },
                        { name: 'strong_sell', count: 0 },
                      ]}
                      value={ratings}
                      onChange={(next) => replaceAiUrl({ ratings: normalizeStringList(next, { lower: true }), page: 1 })}
                      labelClassName="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                    />
                  </FilterGroup>

                  <FilterGroup title="Model confidence">
                    <MultiSelect
                      label="Model confidence"
                      hideLabel
                      options={[
                        { name: 'low', count: 0 },
                        { name: 'medium', count: 0 },
                        { name: 'high', count: 0 },
                      ]}
                      value={confidences}
                      onChange={(next) => replaceAiUrl({ confidences: normalizeStringList(next, { lower: true }), page: 1 })}
                      labelClassName="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                    />
                  </FilterGroup>

                  <FilterGroup title="Sector">
                    <MultiSelect
                      label="Sector"
                      hideLabel
                      options={(sectorsData || []).map((s) => ({ name: s, count: 0 }))}
                      value={sectors}
                      onChange={(next) => replaceAiUrl({ sectors: normalizeStringList(next), page: 1 })}
                      labelClassName="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                    />
                  </FilterGroup>

                  <FilterGroup title="Nearest scenario">
                    <MultiSelect
                      label="Nearest scenario"
                      hideLabel
                      options={[
                        { name: 'bull', count: 0 },
                        { name: 'base', count: 0 },
                        { name: 'bear', count: 0 },
                      ]}
                      value={nearestScenarios}
                      onChange={(next) => replaceAiUrl({ nearest_scenarios: normalizeStringList(next, { lower: true }), page: 1 })}
                      labelClassName="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                    />
                  </FilterGroup>

                  <FilterGroup title="Proximity">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <label htmlFor="aiDeltaBaseMin" className="text-[11px] font-semibold text-muted-foreground">
                          Delta base min (%)
                        </label>
                        <input
                          id="aiDeltaBaseMin"
                          inputMode="decimal"
                          value={deltaBaseMinRaw}
                          onChange={(e) => replaceAiUrl({ delta_base_pct_min: e.currentTarget.value, page: 1 })}
                          placeholder="e.g., 10"
                          className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label htmlFor="aiDeltaBaseMax" className="text-[11px] font-semibold text-muted-foreground">
                          Delta base max (%)
                        </label>
                        <input
                          id="aiDeltaBaseMax"
                          inputMode="decimal"
                          value={deltaBaseMaxRaw}
                          onChange={(e) => replaceAiUrl({ delta_base_pct_max: e.currentTarget.value, page: 1 })}
                          placeholder="e.g., 50"
                          className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label htmlFor="aiNearestDistanceMax" className="text-[11px] font-semibold text-muted-foreground">
                          Distance max (%)
                        </label>
                        <input
                          id="aiNearestDistanceMax"
                          inputMode="decimal"
                          value={nearestDistanceMaxRaw}
                          onChange={(e) => replaceAiUrl({ nearest_distance_pct_max: e.currentTarget.value, page: 1 })}
                          placeholder="e.g., 5"
                          className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label htmlFor="aiBaseProbMin" className="text-[11px] font-semibold text-muted-foreground">
                          Base prob min (%)
                        </label>
                        <input
                          id="aiBaseProbMin"
                          inputMode="decimal"
                          value={baseProbMinRaw}
                          onChange={(e) => replaceAiUrl({ base_probability_pct_min: e.currentTarget.value, page: 1 })}
                          placeholder="e.g., 60"
                          className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                    </div>
                  </FilterGroup>

                </FilterSidebar>
              </div>
            </CardContent>
          </Card>
        </aside>

        <main className="mt-0 space-y-6 lg:mt-0">
          <Card ref={resultsTopRef} id="ai-results-top" className="border-outline/8">
            <CardHeader className="relative">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="space-y-1">
                  <CardTitle>Results</CardTitle>
                  {isError ? (
                    <InlineError
                      message="Couldn't load analyses."
                      onRetry={() => void refetch()}
                      className="mt-2"
                    />
                  ) : (
                    <CardDescription>
                      {isLoading ? (
                        <>Loading…</>
                      ) : total ? (
                        <>
                          Showing {rangeStart}-{rangeEnd} of {total} • Sorted by: {sortLabel}
                          {countDelta ? (
                            <span className="ml-2 inline-flex items-center">
                              <Badge variant="secondary" className="text-[11px]">
                                {countDelta}
                              </Badge>
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <>
                          {symbol ? `No results for ${symbol}.` : 'No AI analyses available yet.'} • Sorted by: {sortLabel}
                        </>
                      )}
                    </CardDescription>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Sort</span>
                  <select
                    value={aiSortBy}
                    onChange={(e) => {
                      const next = e.target.value as 'date' | 'symbol'
                      const order = next === 'symbol' ? 'asc' : 'desc'
                      const nextChoice = `${next}_${order}` as NonNullable<AiAnalysisPersistedFilters['sortChoice']>
                      setSortChoice(nextChoice)
                      replaceAiUrl({ sortChoice: nextChoice, page: 1 })
                    }}
                    className="h-9 rounded-md border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring sm:text-sm"
                  >
                    <option value="date">Date</option>
                    <option value="symbol">Symbol</option>
                  </select>
                  <button
                    className="rounded-md border px-2 py-1 text-xs hover:bg-accent"
                    title="Toggle sort order"
                    onClick={() => {
                      const nextOrder = aiSortOrder === 'asc' ? 'desc' : 'asc'
                      const nextChoice = `${aiSortBy}_${nextOrder}` as NonNullable<AiAnalysisPersistedFilters['sortChoice']>
                      setSortChoice(nextChoice)
                      replaceAiUrl({ sortChoice: nextChoice, page: 1 })
                    }}
                  >
                    {aiSortOrder === 'asc' ? 'Asc ↑' : 'Desc ↓'}
                  </button>
                  {totalPages > 1 ? (
                    <>
                      <button
                        className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                        disabled={page <= 1}
                        onClick={() => replaceAiUrl({ page: Math.max(1, page - 1) })}
                      >
                        Prev
                      </button>
                      <span className="text-xs sm:text-sm">Page {page} / {totalPages}</span>
                      <button
                        className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                        disabled={page >= totalPages}
                        onClick={() => replaceAiUrl({ page: Math.min(totalPages, page + 1) })}
                      >
                        Next
                      </button>
                    </>
                  ) : null}
                </div>
              </div>
            </CardHeader>
            <CardContent className="relative">
              {isLoading || isError || items.length === 0 ? (
                <DataStateWrapper
                  status={isLoading ? 'loading' : isError ? 'error' : 'empty'}
                  context="ai-analysis"
                  loadingLabel="Loading AI feed…"
                  title={isError ? 'Data temporarily unavailable' : 'No results'}
                  message={
                    isError
                      ? 'Failed to load AI analyses.'
                      : symbol
                        ? `No results for ${symbol}.`
                        : 'No AI analyses available yet.'
                  }
                  lastUpdated={lastUpdatedLabel}
                  filters={activeFilterChips.map((chip) => ({ key: chip.key, label: chip.label, onRemove: chip.onRemove }))}
                  onClearFilters={activeFilterChips.length ? resetAllFilters : undefined}
                  clearFiltersLabel="Reset filters"
                  tips={
                    activeFilterChips.length
                      ? ['Clear a filter to broaden the feed.', 'Try removing a date range or proximity filter.']
                      : ['Check back after the next pipeline refresh.', 'Try again in a few minutes.']
                  }
                  onRetry={isError ? () => void refetch() : undefined}
                  error={analysisErrorRaw}
                />
              ) : (
                <div className="space-y-3">
                  {items.map((it) => (
                    <AiRow key={it.analysis_id} item={it} />
                  ))}
                </div>
              )}
              {items.length > 0 && totalPages > 1 ? (
                <div className="mt-4 flex flex-wrap items-center justify-end gap-2 text-sm">
                  <button
                    className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                    disabled={page <= 1}
                    onClick={() => replaceAiUrl({ page: Math.max(1, page - 1) })}
                  >
                    Prev
                  </button>
                  <span className="text-xs sm:text-sm">Page {page} / {totalPages}</span>
                  <button
                    className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                    disabled={page >= totalPages}
                    onClick={() => replaceAiUrl({ page: Math.min(totalPages, page + 1) })}
                  >
                    Next
                  </button>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </main>
      </div>
    </div>
  )
}

function AiRow({ item }: { item: AiAnalysisItem }) {
  const router = useRouter()
  const symbol = (item.symbol || '').trim().toUpperCase()
  const analysisId = (item.analysis_id || '').toString().trim()
  const rowId = `ai-analysis-row-${item.analysis_id}`
  const ratingTone = getRatingTone(item.overall_rating)
  const confidenceTone = getConfidenceTone(item.confidence)
  const base = fmtCaseFields(item.base_price_target, item.base_probability_pct)
  const baseLine = fmtBaseCaseLine(item.base_price_target, item.base_probability_pct)
  const spreadLine = fmtBullBearSpread({
    bullDelta: item.delta_bull_pct,
    bearDelta: item.delta_bear_pct,
    basePt: item.base_price_target,
    bullPt: item.bull_price_target,
    bearPt: item.bear_price_target,
  })
  const humanTargetBucket = item.human_target_vs_ra || computeHumanTargetBucket(item)
  const humanTargetMeta = getHumanTargetBucketMeta(humanTargetBucket)
  const scenarioStrip = [
    fmtScenarioStrip('Bull Target', item.bull_price_target, item.bull_probability_pct),
    fmtScenarioStrip('Base Target', item.base_price_target, item.base_probability_pct),
    fmtScenarioStrip('Bear Target', item.bear_price_target, item.bear_probability_pct),
  ]
  const thesis = buildThesis(item)
  const updatedLabel = item.as_of_date ? `Updated ${formatEasternDate(item.as_of_date)}` : 'Updated -'
  return (
    <ClickableCard
      id={rowId}
      onActivate={() => {
        if (!symbol) return
        writeSessionStorageItem('rankalpha.focusReturnId', rowId)
        rememberTickerOrigin('ai-analysis')
        router.push(`/ticker/${encodeURIComponent(symbol)}`)
      }}
      className="w-full rounded-2xl border border-outline/10 bg-secondary/15 p-3 text-left shadow-sm hover:border-outline/16 hover:bg-secondary/20 sm:p-4"
    >
      <div className="flex items-start gap-3">
        <div className="mt-1 flex w-8 shrink-0 justify-center">
          <CompareCheckbox symbol={symbol} tooltipVariant="compact" />
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-base font-semibold sm:text-lg">{symbol || '-'}</span>
                {item.overall_rating ? (
                  <Badge variant={ratingTone} className="px-2 py-0.5 text-[11px]">
                    Recommendation: {item.overall_rating}
                  </Badge>
                ) : null}
                {item.confidence ? (
                  <Badge variant={confidenceTone} className="px-2 py-0.5 text-[11px]">
                    Model confidence: {item.confidence}
                  </Badge>
                ) : null}
              </div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground sm:text-sm">{item.company_name || '-'}</div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="hidden flex-col items-end rounded-xl border border-outline/10 bg-card px-3 py-2 text-xs sm:flex">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Base case</div>
                <div className="mt-0.5 font-semibold text-foreground">{base.price || '-'}</div>
                <div className="text-[11px] text-muted-foreground">{base.prob || '-'}</div>
              </div>

              {symbol ? (
                <>
                  <Button
                    type="button"
                    size="sm"
                    className="h-8 rounded-full px-3 text-xs"
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      writeSessionStorageItem('rankalpha.focusReturnId', rowId)
                      rememberTickerOrigin('ai-analysis')
                      const href = analysisId
                        ? `/ai-analysis/id/${encodeURIComponent(analysisId)}`
                        : `/ai-analysis/${encodeURIComponent(symbol)}`
                      router.push(href)
                    }}
                    aria-label={`Open AI memo for ${symbol}`}
                  >
                    Open AI Memo
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full px-3 text-xs"
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      writeSessionStorageItem('rankalpha.focusReturnId', rowId)
                      rememberTickerOrigin('ai-analysis')
                      router.push(`/ticker/${encodeURIComponent(symbol)}`)
                    }}
                    aria-label={`Open ticker details for ${symbol}`}
                  >
                    Open ticker
                  </Button>
                </>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold text-muted-foreground">
            <span>{updatedLabel}</span>
            {item.recommendation_timeframe ? (
              <span className="rounded-full border border-outline/10 bg-card px-2.5 py-1">
                Horizon {item.recommendation_timeframe}
              </span>
            ) : null}
            {humanTargetMeta ? (
              <span className={humanTargetMeta.className}>
                <humanTargetMeta.Icon className="h-3.5 w-3.5" aria-hidden />
                {humanTargetMeta.label}
              </span>
            ) : null}
            <span className="sm:hidden rounded-full border border-outline/10 bg-card px-2.5 py-1">
              Base {base.price || '-'} · {base.prob || '-'}
            </span>
          </div>

          <div className="space-y-1 text-xs text-muted-foreground">
            <div>Base case: {baseLine}</div>
            <div>Bull/Bear spread: {spreadLine}</div>
          </div>

          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-outline/10 bg-card px-2.5 py-2 text-[11px] text-muted-foreground">
            <span className="font-semibold uppercase tracking-wide text-foreground">Scenario probabilities</span>
            {scenarioStrip.map((s) => (
              <span key={s.label} className="rounded-full border border-outline/10 bg-background px-2 py-0.5">
                {s.label}: {s.value}
              </span>
            ))}
          </div>

          <div className={cn('text-sm leading-relaxed text-muted-foreground', thesis ? 'line-clamp-2' : null)}>
            {thesis || 'No summary yet.'}
          </div>
        </div>
      </div>
    </ClickableCard>
  )
}

function fmtCaseFields(pt?: number, prob?: number) {
  let price: string | undefined
  if (pt !== null && pt !== undefined && !Number.isNaN(Number(pt))) {
    price = `$${Math.round(Number(pt))}`
  }
  let p: string | undefined
  if (prob !== null && prob !== undefined && !Number.isNaN(Number(prob))) {
    p = `p=${Math.round(Number(prob))}%`
  }
  return { price, prob: p }
}

function fmtBaseCaseLine(pt?: number, prob?: number) {
  const price = fmtPriceTarget(pt)
  const probability = fmtProbability(prob)
  return `${price} (p=${probability})`
}

function fmtScenarioStrip(label: string, pt?: number, prob?: number) {
  const price = fmtPriceTarget(pt)
  const probability = fmtProbability(prob)
  return { label, value: `${price} (p=${probability})` }
}

function buildThesis(item: AiAnalysisItem): string | null {
  const preferred =
    (item.overall_rating || '').toLowerCase().includes('bear') ? item.analyst_summary?.bear_case : item.analyst_summary?.bull_case
  const seed =
    cleanParagraph(preferred) ||
    cleanParagraph(item.analyst_summary?.valuation_check) ||
    cleanParagraph(extractNarrativeFromCommentary(item.commentary)) ||
    cleanParagraph(item.commentary)
  if (!seed) return null
  return takeSentences(seed, 2)
}

function extractNarrativeFromCommentary(commentary?: string | null): string | null {
  const raw = (commentary || '').trim()
  if (!raw) return null

  if ((raw.startsWith('{') && raw.endsWith('}')) || (raw.startsWith('[') && raw.endsWith(']'))) {
    try {
      const parsed = JSON.parse(raw) as any
      const candidates = [
        parsed?.thesis,
        parsed?.summary,
        parsed?.commentary,
        parsed?.sentiment_commentary,
        parsed?.bull_case,
        parsed?.bear_case,
        parsed?.base_case,
      ].filter((v) => typeof v === 'string') as string[]
      const best = candidates.map(cleanParagraph).filter(Boolean)[0]
      return best || null
    } catch {
      // ignore
    }
  }

  const lines = raw.split('\n').map((l) => l.trim()).filter(Boolean)
  const kv: Record<string, string> = {}
  for (const line of lines) {
    const m = line.match(/^\s*"?([A-Za-z0-9_ -]{2,})"?\s*:\s*(.+)\s*$/)
    if (!m) continue
    const key = m[1].toLowerCase().replace(/\s+/g, '_').trim()
    const value = m[2].trim()
    if (value) kv[key] = value
  }
  const preferredKeys = ['thesis', 'summary', 'commentary', 'sentiment_commentary', 'bull_case', 'bear_case', 'base_case']
  for (const k of preferredKeys) {
    if (kv[k]) return kv[k]
  }
  return null
}

function takeSentences(text: string, maxSentences: number): string {
  const cleaned = cleanParagraph(text)
  if (!cleaned) return ''
  const parts = cleaned
    .split(/(?<=[.!?])\s+/)
    .map((p) => p.trim())
    .filter(Boolean)
  const joined = parts.slice(0, Math.max(1, maxSentences)).join(' ')
  return truncate(joined, 280)
}

function cleanParagraph(text?: string | null): string {
  if (!text) return ''
  const s = String(text)
    .replace(/\r/g, '')
    .replace(/"([A-Za-z0-9_]+)"\s*:/g, '')
    .replace(/\b[A-Za-z0-9_]+\s*:\s*/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return s
}

function truncate(text: string, maxLen: number): string {
  const s = (text || '').trim()
  if (s.length <= maxLen) return s
  return `${s.slice(0, Math.max(0, maxLen - 1)).trim()}…`
}

function getRatingTone(rating?: string): BadgeProps['variant'] {
  const raw = rating?.toLowerCase() || ''
  if (raw.includes('bull') || raw.includes('positive')) {
    return 'success'
  }
  if (raw.includes('bear') || raw.includes('negative')) {
    return 'danger'
  }
  if (raw.includes('neutral')) {
    return 'warning'
  }
  return 'secondary'
}

function getConfidenceTone(confidence?: string): BadgeProps['variant'] {
  const raw = confidence?.toLowerCase() || ''
  if (raw.includes('high')) return 'success'
  if (raw.includes('low')) return 'danger'
  if (raw.includes('med')) return 'warning'
  return 'secondary'
}

// items are already latest-per-symbol when latest_only_per_symbol=true
