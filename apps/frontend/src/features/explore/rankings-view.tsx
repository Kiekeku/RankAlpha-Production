'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge, badgeVariants, type BadgeProps } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ClickableCard } from '@/components/interaction/clickable_card'
import { ClickableTableRow } from '@/components/interaction/clickable_table_row'
import { Button } from '@/components/ui/button'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { PageHeader } from '@/components/page-header'
import { DataTable } from '@/components/ui/data-table'
import { ChevronDownIcon, ExternalLinkIcon, FilterIcon, AlertTriangleIcon, ArrowUpIcon, ArrowDownIcon, CopyIcon, LayoutGridIcon, Table2Icon } from 'lucide-react'
import { api, type AiPreview, type StockGradeItem, ModelWeights, SetupChip, SetupDeveloping, SetupSummaryItem } from '@/lib/api'
import { cn, formatScore } from '@/lib/utils'
import { readLocalStorageJson, removeLocalStorageItem, writeLocalStorageJson, writeSessionStorageItem } from '@/lib/storage'
import { CompareCheckbox } from '@/components/compare/compare_checkbox'
import { CompareCheckboxCell } from '@/components/compare/compare_checkbox_cell'
import { buildComparePageUrl, useCompare } from '@/components/compare/compare_context'
import { useCountDeltaBadge } from '@/lib/use_count_delta'
import { useFactors } from '@/components/factors/factors_context'
import { TooltipCopy, TooltipCopyContent } from '@/components/tooltip_copy'
import { formatEasternDate } from '@/lib/date'
import { formatNumberValue } from '@/lib/format'
import { UI_TERMS, formatSetupHitsLabel, formatSetupTag } from '@/lib/ui_terms'
import { SavedViewsDialog } from '@/components/saved-views/saved_views_dialog'
import { DataStateWrapper } from '@/components/data-state-wrapper'
import { DataFooter } from '@/components/data-footer'
import { InlineError } from '@/components/ui/inline-error'
import { ColumnHeaderTooltip } from '@/components/column-header-tooltip'
import { rememberTickerOrigin } from '@/lib/ticker_nav'
import { useMediaQuery } from '@/lib/use_media_query'
import { ActiveFilterChips } from '@/components/filters/ActiveFilterChips'
import { FilterGroup, FilterSidebar } from '@/components/filters/FilterSidebar'
import { useFilterRailState } from '@/components/filters/use_filter_rail_state'
import { RankingsTabs } from '@/components/rankings/rankings_tabs'
import { SavedViewsButton } from '@/components/saved-views/saved_views_button'
import { useSavedViewsDrawer, useSavedViewsLinks } from '@/components/saved-views/use_saved_views_drawer'
import { useShareCurrentView } from '@/components/saved-views/use_share_current_view'
import { useLoadSavedView } from '@/components/saved-views/use_load_saved_view'
import { DensityToggle } from '@/components/density-toggle'
import { MiniSparkline } from '@/components/charts/mini-sparkline'
import { useUiDensity } from '@/lib/ui_density'
import { fetchSparklinePriceMap } from '@/lib/sparklines'

type SortBy = 'grade' | 'momentum' | 'value' | 'sentiment' | 'symbol'
type SortOrder = 'asc' | 'desc'

type SetupBiasFilter = 'both' | 'bullish' | 'bearish'
type SetupLogic = 'any' | 'all'
const setupOptions = [
  { slug: 'momentum', label: 'Momentum' },
  { slug: 'breakout', label: 'Breakout' },
  { slug: 'growth', label: 'Growth' },
  { slug: 'mean_reversion', label: 'Mean Reversion' },
  { slug: 'pullback', label: 'Pullback' },
  { slug: 'defensive', label: 'Defensive' },
  { slug: 'value', label: 'Value' },
  { slug: 'short', label: 'Short' },
  { slug: 'earnings', label: 'Earnings' },
] as const

type RankingsPersistedFilters = {
  sortBy?: SortBy
  sortOrder?: SortOrder
  selectedGrade?: string
  selectedSector?: string
  hasSetupOnly?: boolean
  setupStyles?: string[]
  setupBias?: SetupBiasFilter
  setupLogic?: SetupLogic
}

const RANKINGS_FILTERS_STORAGE_KEY = 'rankalpha.rankings.filters.v1'
const RANKINGS_SAVED_VIEWS_KEY = 'rankalpha.rankings.saved_views.v1'
const RANKINGS_VIEW_STORAGE_KEY = 'rankalpha.rankingsView'
const RANKINGS_FILTERS_COLLAPSED_KEY = 'rankalpha.rankings.filtersCollapsed.v1'
const RANKINGS_SPARKS_STORAGE_KEY = 'rankalpha.rankings.sparklines.v1'
const SETUP_WINDOW_DAYS = 3

const DEFAULT_SORT_BY: SortBy = 'grade'
const DEFAULT_SORT_ORDER: SortOrder = 'desc'

function parseSortBy(raw: string | null): SortBy | null {
  const v = (raw || '').trim().toLowerCase()
  if (!v) return null
  if (v === 'grade' || v === 'momentum' || v === 'value' || v === 'sentiment' || v === 'symbol') return v
  return null
}

function parseSortOrder(raw: string | null): SortOrder | null {
  const v = (raw || '').trim().toLowerCase()
  if (!v) return null
  if (v === 'asc' || v === 'desc') return v
  return null
}

function normalizeGrade(raw: string | null): string {
  const v = (raw || '').trim().toUpperCase()
  return ['A', 'B', 'C', 'D', 'F'].includes(v) ? v : ''
}

function normalizeSector(raw: string | null): string {
  return (raw || '').trim()
}

function normalizeQuery(raw: string | null): string {
  return (raw || '').trim()
}

function normalizePage(raw: string | null): number {
  const n = Number(raw)
  if (!Number.isFinite(n)) return 1
  const i = Math.floor(n)
  return i >= 1 ? i : 1
}

function buildEffectiveWeights(weights: ModelWeights | null | undefined, scores: { momentum?: number; value?: number; sentiment?: number }) {
  const w = weights
    ? { momentum: weights.w_momentum, value: weights.w_value, sentiment: weights.w_sentiment }
    : { momentum: 0.4, value: 0.4, sentiment: 0.2 }
  const present = {
    momentum: Number.isFinite(scores.momentum),
    value: Number.isFinite(scores.value),
    sentiment: Number.isFinite(scores.sentiment),
  }
  const total =
    (present.momentum ? w.momentum : 0) +
    (present.value ? w.value : 0) +
    (present.sentiment ? w.sentiment : 0)
  if (!total) return { momentum: 0, value: 0, sentiment: 0 }
  return {
    momentum: present.momentum ? w.momentum / total : 0,
    value: present.value ? w.value / total : 0,
    sentiment: present.sentiment ? w.sentiment / total : 0,
  }
}

function buildContributionRows(weights: ModelWeights | null | undefined, scores: { momentum?: number; value?: number; sentiment?: number }) {
  const eff = buildEffectiveWeights(weights, scores)
  const rows = [
    { key: 'Momentum', weight: eff.momentum, score: Number(scores.momentum) },
    { key: 'Value', weight: eff.value, score: Number(scores.value) },
    { key: 'Sentiment', weight: eff.sentiment, score: Number(scores.sentiment) },
  ]
    .filter((r) => r.weight > 0 && Number.isFinite(r.score))
    .map((r) => ({ ...r, contrib: r.weight * r.score }))
  const total = rows.reduce((acc, r) => acc + r.contrib, 0) || 1
  return rows.map((r) => ({ ...r, pct: r.contrib / total }))
}

export function RankingsView() {
  const compare = useCompare()
  const router = useRouter()
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const factors = useFactors()
  const { density, setDensity } = useUiDensity('comfortable')
  const [currentPage, setCurrentPage] = useState(1)
  const [sortBy, setSortBy] = useState<SortBy>('grade')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc') // Start with best grades first
  const [selectedGrade, setSelectedGrade] = useState<string>('')
  const [selectedSector, setSelectedSector] = useState<string>('')
  const [searchTerm, setSearchTerm] = useState('')
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const [rankingsView, setRankingsView] = useState<'compact' | 'cards'>('compact')
  const [showSparklines, setShowSparklines] = useState(false)
  const resultsTopRef = useRef<HTMLDivElement | null>(null)
  const { collapsed: filtersCollapsed, setCollapsed: setFiltersCollapsed } = useFilterRailState(
    RANKINGS_FILTERS_COLLAPSED_KEY,
  )
  const isMobile = useMediaQuery(
    '(max-width: 767px)',
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 767px)').matches : false
  )
  const effectiveDensity = isMobile ? 'comfortable' : density
  const isDense = effectiveDensity === 'dense'
  const hasAppliedDefaultView = useRef(false)
  const hasInitializedSparks = useRef(false)
  const { viewsOpen, openViews, onOpenChange } = useSavedViewsDrawer({
    pathname,
    fallbackPath: '/rankings',
    searchParams,
    router,
  })
  const urlQuery = useMemo(() => normalizeQuery(searchParams.get('q')), [searchParams])

  useEffect(() => {
    if (hasInitializedSparks.current) return
    const persisted = readLocalStorageJson<{ v: 1; enabled: boolean }>(RANKINGS_SPARKS_STORAGE_KEY)
    const initial = typeof persisted?.enabled === 'boolean' ? persisted.enabled : false
    setShowSparklines(initial)
    hasInitializedSparks.current = true
  }, [])

  useEffect(() => {
    writeLocalStorageJson(RANKINGS_SPARKS_STORAGE_KEY, { v: 1, enabled: showSparklines })
  }, [showSparklines])

  const pageSize = 25
  const normalizedSearch = urlQuery
  const normalizedSearchLower = normalizedSearch.toLowerCase()
  const setupWindowDays = SETUP_WINDOW_DAYS
  const setupStreakDays = 2
  const setupLabelBySlug = useMemo(
    () => new Map<string, string>(setupOptions.map((opt) => [opt.slug, opt.label])),
    []
  )
  const hasInitializedRef = useRef(false)
  const isApplyingUrlRef = useRef(false)

  const hasSetupOnly = useMemo(() => {
    const raw = (searchParams.get('has_setup') || '').trim().toLowerCase()
    return raw === '1' || raw === 'true' || raw === 'yes'
  }, [searchParams])

  const setupStyles = useMemo(() => {
    const raw = (searchParams.get('setup') || '').trim()
    if (!raw) return []
    return raw.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean)
  }, [searchParams])

  const setupBias: SetupBiasFilter = useMemo(() => {
    const raw = (searchParams.get('setup_bias') || 'both').trim().toLowerCase()
    return raw === 'bullish' || raw === 'bearish' ? raw : 'both'
  }, [searchParams])

  const setupLogic: SetupLogic = useMemo(() => {
    const raw = (searchParams.get('setup_logic') || 'any').trim().toLowerCase()
    return raw === 'all' ? 'all' : 'any'
  }, [searchParams])

  const resultsScrollKey = useMemo(() => {
    return [
      normalizedSearch,
      selectedGrade,
      selectedSector,
      hasSetupOnly ? '1' : '0',
      setupStyles.join(','),
      setupBias,
      setupLogic,
      sortBy,
      sortOrder,
    ].join('|')
  }, [
    normalizedSearch,
    selectedGrade,
    selectedSector,
    hasSetupOnly,
    setupStyles,
    setupBias,
    setupLogic,
    sortBy,
    sortOrder,
  ])

  const replaceRankingsUrl = useCallback((next: Partial<{
    q: string
    grade: string
    sector: string
    sortBy: SortBy
    sortOrder: SortOrder
    page: number
    hasSetupOnly: boolean
    setupStyles: string[]
    setupBias: SetupBiasFilter
    setupLogic: SetupLogic
  }>) => {
    const basePath = pathname || '/rankings'
    const q = next.q ?? normalizedSearch
    const grade = next.grade ?? selectedGrade
    const sector = next.sector ?? selectedSector
    const sb = next.sortBy ?? sortBy
    const so = next.sortOrder ?? sortOrder
    const page = next.page ?? currentPage
    const hasSetup = typeof next.hasSetupOnly === 'boolean' ? next.hasSetupOnly : hasSetupOnly
    const styles = next.setupStyles ?? setupStyles
    const bias = next.setupBias ?? setupBias
    const logic = next.setupLogic ?? setupLogic

    const params = new URLSearchParams()
    if (q.trim()) params.set('q', q.trim())
    if (grade.trim()) params.set('grade', grade.trim())
    if (sector.trim()) params.set('sector', sector.trim())
    if (sb !== DEFAULT_SORT_BY) params.set('sort_by', sb)
    if (so !== DEFAULT_SORT_ORDER) params.set('sort_order', so)
    if (page > 1) params.set('page', String(page))

    if (viewsOpen) params.set('views', '1')
    if (hasSetup) params.set('has_setup', '1')
    if (styles.length) {
      params.set('setup', styles.join(','))
      if (bias !== 'both') params.set('setup_bias', bias)
      if (logic !== 'any') params.set('setup_logic', logic)
    }

    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    const currentUrl = searchParams.toString() ? `${basePath}?${searchParams.toString()}` : basePath
    if (nextUrl === currentUrl) return
    router.replace(nextUrl, { scroll: false })
  }, [
    pathname,
    normalizedSearch,
    selectedGrade,
    selectedSector,
    sortBy,
    sortOrder,
    currentPage,
    hasSetupOnly,
    setupStyles,
    setupBias,
    setupLogic,
    viewsOpen,
    searchParams,
    router,
  ])

  const updateSetupQuery = (next: { styles?: string[]; bias?: SetupBiasFilter; logic?: SetupLogic }) => {
    const nextStyles = next.styles ?? setupStyles
    const nextBias = next.bias ?? setupBias
    const nextLogic = next.logic ?? setupLogic
    replaceRankingsUrl({
      page: 1,
      setupStyles: nextStyles,
      setupBias: nextBias,
      setupLogic: nextLogic,
    })
    setCurrentPage(1)
  }

  const updateHasSetupOnly = (enabled: boolean) => {
    replaceRankingsUrl({ page: 1, hasSetupOnly: enabled })
    setCurrentPage(1)
  }

  const replaceSetupParams = (next: {
    hasSetupOnly?: boolean
    styles?: string[]
    bias?: SetupBiasFilter
    logic?: SetupLogic
  }) => {
    const params = new URLSearchParams(searchParams.toString())

    if (typeof next.hasSetupOnly === 'boolean') {
      if (next.hasSetupOnly) params.set('has_setup', '1')
      else params.delete('has_setup')
    }

    const nextStyles = next.styles ?? setupStyles
    const nextBias = next.bias ?? setupBias
    const nextLogic = next.logic ?? setupLogic

    if (!nextStyles.length) {
      params.delete('setup')
      params.delete('setup_bias')
      params.delete('setup_logic')
    } else {
      params.set('setup', nextStyles.join(','))
      if (nextBias === 'both') params.delete('setup_bias')
      else params.set('setup_bias', nextBias)
      if (nextLogic === 'any') params.delete('setup_logic')
      else params.set('setup_logic', nextLogic)
    }

    const qs = params.toString()
    const basePath = pathname || window.location.pathname
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl)
    setCurrentPage(1)
  }

  useEffect(() => {
    const initialPage = normalizePage(searchParams.get('page'))
    setCurrentPage(initialPage)

    const initialQuery = normalizeQuery(searchParams.get('q'))
    setSearchTerm(initialQuery)

    const initialGrade = normalizeGrade(searchParams.get('grade'))
    if (initialGrade) setSelectedGrade(initialGrade)

    const initialSector = normalizeSector(searchParams.get('sector'))
    if (initialSector) setSelectedSector(initialSector)

    const initialSortBy = parseSortBy(searchParams.get('sort_by'))
    const initialSortOrder = parseSortOrder(searchParams.get('sort_order'))
    if (initialSortBy) setSortBy(initialSortBy)
    if (initialSortOrder) setSortOrder(initialSortOrder)

    const persisted = readLocalStorageJson<RankingsPersistedFilters>(RANKINGS_FILTERS_STORAGE_KEY)
    const hasUrlCoreParams =
      Boolean(searchParams.get('q')) ||
      Boolean(searchParams.get('grade')) ||
      Boolean(searchParams.get('sector')) ||
      Boolean(searchParams.get('sort_by')) ||
      Boolean(searchParams.get('sort_order')) ||
      Boolean(searchParams.get('page'))

    if (persisted && !hasUrlCoreParams) {
      if (
        persisted.sortBy &&
        ['grade', 'momentum', 'value', 'sentiment', 'symbol'].includes(persisted.sortBy)
      ) {
        setSortBy(persisted.sortBy)
      }
      if (persisted.sortOrder && (persisted.sortOrder === 'asc' || persisted.sortOrder === 'desc')) {
        setSortOrder(persisted.sortOrder)
      }
      if (typeof persisted.selectedGrade === 'string') setSelectedGrade(persisted.selectedGrade)
      if (typeof persisted.selectedSector === 'string') setSelectedSector(persisted.selectedSector)

      const hasUrlSetupParams =
        Boolean(searchParams.get('has_setup')) ||
        Boolean(searchParams.get('setup')) ||
        Boolean(searchParams.get('setup_bias')) ||
        Boolean(searchParams.get('setup_logic'))

      if (!hasUrlSetupParams) {
        const persistedSetupStyles = Array.isArray(persisted.setupStyles)
          ? persisted.setupStyles.map((s) => (s || '').trim().toLowerCase()).filter(Boolean)
          : []
        const validSetupStyles = setupOptions.map((opt) => opt.slug).filter((s) => persistedSetupStyles.includes(s))
        const setupBias: SetupBiasFilter =
          persisted.setupBias === 'bullish' || persisted.setupBias === 'bearish' ? persisted.setupBias : 'both'
        const setupLogic: SetupLogic = persisted.setupLogic === 'all' ? 'all' : 'any'
        replaceSetupParams({
          hasSetupOnly: Boolean(persisted.hasSetupOnly),
          styles: validSetupStyles,
          bias: setupBias,
          logic: setupLogic,
        })
      }
    }

    const persistedView = readLocalStorageJson<string>(RANKINGS_VIEW_STORAGE_KEY)
    if (persistedView === 'compact' || persistedView === 'cards') {
      setRankingsView(persistedView)
      hasAppliedDefaultView.current = true
      hasInitializedRef.current = true
      return
    }

    if (typeof window !== 'undefined') {
      setRankingsView(isMobile ? 'cards' : 'compact')
      hasAppliedDefaultView.current = true
      hasInitializedRef.current = true
      return
    }

    hasInitializedRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (hasAppliedDefaultView.current) return
    const persistedView = readLocalStorageJson<string>(RANKINGS_VIEW_STORAGE_KEY)
    if (persistedView === 'compact' || persistedView === 'cards') return
    setRankingsView(isMobile ? 'cards' : 'compact')
    hasAppliedDefaultView.current = true
  }, [isMobile])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    isApplyingUrlRef.current = true
    const page = normalizePage(searchParams.get('page'))
    const q = normalizeQuery(searchParams.get('q'))
    const grade = normalizeGrade(searchParams.get('grade'))
    const sector = normalizeSector(searchParams.get('sector'))
    const sb = parseSortBy(searchParams.get('sort_by')) ?? DEFAULT_SORT_BY
    const so = parseSortOrder(searchParams.get('sort_order')) ?? DEFAULT_SORT_ORDER

    setCurrentPage(page)
    setSearchTerm(q)
    setSelectedGrade(grade)
    setSelectedSector(sector)
    setSortBy(sb)
    setSortOrder(so)

    Promise.resolve().then(() => {
      isApplyingUrlRef.current = false
    })
  }, [searchParams])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    writeLocalStorageJson(RANKINGS_FILTERS_STORAGE_KEY, {
      sortBy,
      sortOrder,
      selectedGrade,
      selectedSector,
      hasSetupOnly,
      setupStyles,
      setupBias,
      setupLogic,
    } satisfies RankingsPersistedFilters)
  }, [sortBy, sortOrder, selectedGrade, selectedSector, hasSetupOnly, setupStyles, setupBias, setupLogic])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    writeLocalStorageJson(RANKINGS_VIEW_STORAGE_KEY, rankingsView)
  }, [rankingsView])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    if (isApplyingUrlRef.current) return
    replaceRankingsUrl({ page: currentPage })
  }, [sortBy, sortOrder, selectedGrade, selectedSector, normalizedSearch, currentPage, replaceRankingsUrl])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    const normalizedInput = normalizeQuery(searchTerm)
    if (normalizedInput === urlQuery) return
    const t = window.setTimeout(() => {
      replaceRankingsUrl({ q: normalizedInput, page: 1 })
      setCurrentPage(1)
    }, 250)
    return () => window.clearTimeout(t)
  }, [searchTerm, urlQuery, replaceRankingsUrl])

  useEffect(() => {
    if (!hasInitializedRef.current) return
    if (typeof window === 'undefined') return
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

  // Server-side pagination: fetch exactly one page window respecting filters
  const { data: grades, isLoading: gradesLoading, isError: gradesError, error: gradesErrorRaw, refetch: refetchGrades } = useQuery({
    queryKey: ['all-grades', currentPage, sortBy, sortOrder, selectedGrade, selectedSector, normalizedSearch, hasSetupOnly, setupStyles.join(','), setupBias, setupLogic],
    queryFn: () => api.getStockGrades({
      limit: pageSize,
      skip: (currentPage - 1) * pageSize,
      sort_by: sortBy,
      sort_order: sortOrder,
      min_grade: selectedGrade || undefined,
      max_grade: selectedGrade || undefined,
      sector: selectedSector || undefined,
      search: normalizedSearch || undefined,
      has_setup: hasSetupOnly ? true : undefined,
      setup_styles: setupStyles.length ? setupStyles : undefined,
      setup_bias: setupStyles.length ? setupBias : undefined,
      setup_logic: setupStyles.length ? setupLogic : undefined,
    }),
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
  });

  const { data: modelWeights } = useQuery({
    queryKey: ['model-weights'],
    queryFn: () => api.getModelWeights(),
    staleTime: 10 * 60 * 1000,
  })

  const gradesErrorMessage = useMemo(() => {
    if (!gradesError) return null
    return 'Failed to load rankings. The API may be unavailable or the scoring pipeline may not have produced grades yet.'
  }, [gradesError])

  const openStock = (symbol: string) => {
    const normalized = (symbol || '').trim().toUpperCase()
    if (!normalized) return
    rememberTickerOrigin('rankings')
    const href = `/ticker/${encodeURIComponent(normalized)}`
    router.push(href, { scroll: false })
  }

  const handleFilterChange = () => {
    setCurrentPage(1)
  }

  // Calculate pagination
  const currentStocks = useMemo(() => grades?.stocks ?? [], [grades?.stocks])
  const symbols = useMemo(
    () => Array.from(new Set(currentStocks.map((s) => s.symbol))).filter(Boolean),
    [currentStocks]
  )

  const { data: setupSummaries } = useQuery({
    queryKey: ['setup-summaries', symbols.join(','), setupWindowDays],
    queryFn: () => api.getSetupSummaries(symbols, { window_days: setupWindowDays }),
    enabled: symbols.length > 0,
    staleTime: 60_000,
  })

  const setupBySymbol: Record<string, SetupSummaryItem> = useMemo(() => {
    const items = setupSummaries?.items || []
    const out: Record<string, SetupSummaryItem> = {}
    items.forEach((it) => {
      out[it.symbol] = it
    })
    return out
  }, [setupSummaries])

  const displayStocks = useMemo(() => {
    if (!normalizedSearch) return currentStocks
    return currentStocks.filter((stock) => {
      const symbolMatch = stock.symbol.toLowerCase().includes(normalizedSearchLower)
      const nameMatch = stock.company_name ? stock.company_name.toLowerCase().includes(normalizedSearchLower) : false
      return symbolMatch || nameMatch
    })
  }, [currentStocks, normalizedSearch, normalizedSearchLower])

  const sparklineSymbols = useMemo(() => {
    if (!showSparklines || isMobile || rankingsView !== 'compact') return []
    return displayStocks.map((s) => (s.symbol || '').trim().toUpperCase()).filter(Boolean)
  }, [displayStocks, isMobile, rankingsView, showSparklines])

  const { data: sparklineMap } = useQuery({
    queryKey: ['rankings-sparklines', sparklineSymbols.join(',')],
    queryFn: () => fetchSparklinePriceMap(sparklineSymbols, 40),
    enabled: sparklineSymbols.length > 0,
    staleTime: 120_000,
  })
  const totalPages = Math.ceil((grades?.total_count || 0) / pageSize)
  const totalCount = grades?.total_count ?? 0
  const filterKey = useMemo(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('page')
    return params.toString()
  }, [searchParams])
  const { delta: countDelta } = useCountDeltaBadge(totalCount, filterKey)

  const lastUpdatedLabel = grades?.as_of_date ? formatEasternDate(grades.as_of_date) : null
  const statusLabel = gradesError ? 'Status: delayed' : gradesLoading ? 'Status: loading' : 'Status: live'
  const headerContextBadges = [
    grades?.as_of_date ? `As of ${formatEasternDate(grades.as_of_date)}` : null,
    totalCount ? `Universe ${totalCount.toLocaleString()}` : null,
    statusLabel,
  ].filter(Boolean)

  const activeFilterChips = (() => {
    const chips: Array<{ key: string; label: string; onRemove?: () => void }> = []
    if (normalizedSearch) {
      chips.push({
        key: 'q',
        label: `Search: ${normalizedSearch}`,
        onRemove: () => {
          setSearchTerm('')
          replaceRankingsUrl({ q: '', page: 1 })
          setCurrentPage(1)
        },
      })
    }
    if (selectedGrade) chips.push({
      key: 'grade',
      label: `Grade: ${selectedGrade}`,
      onRemove: () => {
        setSelectedGrade('')
        setCurrentPage(1)
      },
    })
    if (selectedSector) chips.push({
      key: 'sector',
      label: `Sector: ${selectedSector}`,
      onRemove: () => {
        setSelectedSector('')
        setCurrentPage(1)
      },
    })
    if (hasSetupOnly) chips.push({ key: 'has_setup', label: 'Setup-hit streak only', onRemove: () => updateHasSetupOnly(false) })
    if (setupStyles.length) {
      setupStyles.forEach((s) => {
        const readable = setupLabelBySlug.get(s) ?? s
        chips.push({
          key: `setup:${s}`,
          label: `Setup: ${readable}`,
          onRemove: () => updateSetupQuery({ styles: setupStyles.filter((it) => it !== s) }),
        })
      })
      if (setupBias !== 'both') chips.push({ key: 'setup_bias', label: `Bias: ${setupBias}`, onRemove: () => updateSetupQuery({ bias: 'both' }) })
      if (setupLogic === 'all') chips.push({ key: 'setup_logic', label: 'Match all setup hits', onRemove: () => updateSetupQuery({ logic: 'any' }) })
    }
    return chips
  })()

  const hasActiveFilters = activeFilterChips.length > 0

  const resetToDefault = () => {
    removeLocalStorageItem(RANKINGS_FILTERS_STORAGE_KEY)
    setSearchTerm('')
    setSelectedGrade('')
    setSelectedSector('')
    setSortBy(DEFAULT_SORT_BY)
    setSortOrder(DEFAULT_SORT_ORDER)
    replaceRankingsUrl({
      q: '',
      grade: '',
      sector: '',
      sortBy: DEFAULT_SORT_BY,
      sortOrder: DEFAULT_SORT_ORDER,
      page: 1,
      hasSetupOnly: false,
      setupStyles: [],
      setupBias: 'both',
      setupLogic: 'any',
    })
    setCurrentPage(1)
  }

  const applyRankingsPreset = useCallback((preset: 'momentum_longs' | 'earnings_post_momo' | 'value_focus') => {
    const base = {
      q: '',
      grade: '',
      sector: '',
      page: 1,
      sortOrder: 'desc' as SortOrder,
      hasSetupOnly: true,
      setupLogic: 'any' as SetupLogic,
      setupBias: 'both' as SetupBiasFilter,
      setupStyles: [] as string[],
    }

    if (preset === 'momentum_longs') {
      const next = {
        ...base,
        sortBy: 'momentum' as SortBy,
        setupBias: 'bullish' as SetupBiasFilter,
        setupStyles: ['momentum', 'breakout'],
        setupLogic: 'any' as SetupLogic,
      }
      replaceRankingsUrl(next)
      setSortBy(next.sortBy)
      setSortOrder(next.sortOrder)
    } else if (preset === 'earnings_post_momo') {
      const next = {
        ...base,
        sortBy: 'momentum' as SortBy,
        setupBias: 'bullish' as SetupBiasFilter,
        setupStyles: ['earnings', 'momentum'],
        setupLogic: 'all' as SetupLogic,
      }
      replaceRankingsUrl(next)
      setSortBy(next.sortBy)
      setSortOrder(next.sortOrder)
    } else {
      const next = {
        ...base,
        sortBy: 'value' as SortBy,
        setupBias: 'both' as SetupBiasFilter,
        setupStyles: ['value'],
        setupLogic: 'any' as SetupLogic,
      }
      replaceRankingsUrl(next)
      setSortBy(next.sortBy)
      setSortOrder(next.sortOrder)
    }

    setSearchTerm('')
    setSelectedGrade('')
    setSelectedSector('')
    setCurrentPage(1)
  }, [replaceRankingsUrl])

  const rankingsPresets = [
    {
      key: 'momentum-longs',
      label: 'Momentum longs',
      description: 'Bullish momentum/breakout setups.',
      onApply: () => applyRankingsPreset('momentum_longs'),
    },
    {
      key: 'earnings-post-momo',
      label: 'Earnings post-momo',
      description: 'Earnings + momentum setups (both required).',
      onApply: () => applyRankingsPreset('earnings_post_momo'),
    },
    {
      key: 'value-focus',
      label: 'Value focus',
      description: 'Value setups sorted by value score.',
      onApply: () => applyRankingsPreset('value_focus'),
    },
  ]

  const shareCurrentView = useShareCurrentView({
    successDescription: 'Share this rankings view.',
  })

  const { currentSavedViewQuery, savedViewsBasePath, buildSavedViewUrlForQuery } = useSavedViewsLinks({
    pathname,
    fallbackPath: '/rankings',
    searchParams,
  })

  const loadSavedView = useLoadSavedView({
    basePath: savedViewsBasePath,
    router,
  })

  // Proper sector list via API
  const { data: sectors } = useQuery({
    queryKey: ['sectors'],
    queryFn: () => api.listSectors(),
    staleTime: 3_600_000,
  })

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader
        title="Rankings"
        subtitle="Momentum, value, and overall scores for tracked stocks with setup hits. Updated nightly."
        contextBadges={headerContextBadges}
        primaryAction={(
          <PrimaryCtaLink
            href={buildComparePageUrl({
              symbols: compare.symbols,
              baseline: compare.baseline ?? (compare.symbols[0] ?? null),
              mode: 'table',
              deltas: compare.showDeltas,
            })}
          >
            Open Compare
          </PrimaryCtaLink>
        )}
        secondaryActions={[
          (
            <TooltipCopy key="rankings-methodology" tooltipKey="global.methodology">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 rounded-full px-2 text-xs font-semibold text-muted-foreground hover:bg-secondary/40 hover:text-foreground"
                onClick={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  factors.open()
                }}
              >
                Methodology
              </Button>
            </TooltipCopy>
          ),
          <SavedViewsButton key="rankings-saved" onClick={openViews} />,
          (
            <TooltipCopy key="rankings-copy" tooltipKey="global.share">
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
        tabs={<RankingsTabs />}
        activeChips={(
          <div className="rounded-2xl border border-outline/12 bg-background/90 p-3 shadow-sm backdrop-blur">
            <ActiveFilterChips
              chips={activeFilterChips.map((chip) => ({
                ...chip,
                onRemove: chip.onRemove
                  ? () => {
                      chip.onRemove?.()
                      setCurrentPage(1)
                    }
                  : undefined,
              }))}
              onClearAll={resetToDefault}
              clearLabel="Reset filters"
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {filtersCollapsed ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="hidden h-8 rounded-full px-3 text-[11px] lg:inline-flex"
                  onClick={() => setFiltersCollapsed(false)}
                >
                  Show filters
                </Button>
              ) : null}
            </div>
            {rankingsPresets.length ? (
              <div className="mt-3 space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Filter presets</div>
                <div className="flex flex-wrap gap-2">
                  {rankingsPresets.map((preset) => (
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
                storageKey={RANKINGS_SAVED_VIEWS_KEY}
                currentQuery={currentSavedViewQuery}
                buildUrlForQuery={buildSavedViewUrlForQuery}
                onLoad={loadSavedView}
                namePlaceholder="e.g., Tech A momentum"
                helperText="Saved Views store the current URL filters so you can reuse the same screen daily."
                showQueryPreview
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
        <aside className={cn('space-y-4 lg:sticky lg:top-6 lg:self-start', filtersCollapsed && 'lg:hidden')}>
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
                    aria-controls="rankings-filters"
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
            </CardHeader>
            <CardContent className="relative">
              <div
                id="rankings-filters"
                className={cn(
                  'space-y-4',
                  mobileFiltersOpen ? 'block' : 'hidden',
                  'lg:block'
                )}
              >
                <FilterSidebar>
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">Search within the current eligible universe.</p>
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="searchRankings" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Search
                      </label>
                      <input
                        id="searchRankings"
                        type="search"
                        value={searchTerm}
                        onChange={(e) => {
                          setSearchTerm(e.target.value)
                        }}
                        placeholder="Symbol or company"
                        className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        autoComplete="off"
                      />
                    </div>
                  </div>

                  <FilterGroup title="Key dropdowns">
                    <div className="grid gap-3">
                      <div className="flex flex-col gap-1.5">
                        <label htmlFor="gradeFilter" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Grade
                        </label>
                        <select
                          id="gradeFilter"
                          value={selectedGrade}
                          onChange={(e) => {
                            setSelectedGrade(e.target.value)
                            handleFilterChange()
                          }}
                          className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        >
                          <option value="">All Grades</option>
                          <option value="A">A</option>
                          <option value="B">B</option>
                          <option value="C">C</option>
                          <option value="D">D</option>
                          <option value="F">F</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <label htmlFor="sectorFilter" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Sector
                        </label>
                        <select
                          id="sectorFilter"
                          value={selectedSector}
                          onChange={(e) => {
                            setSelectedSector(e.target.value)
                            handleFilterChange()
                          }}
                          className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        >
                          <option value="">All Sectors</option>
                          {(sectors || []).map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </FilterGroup>

                  <FilterGroup title="Liquidity / Price floors">
                    <div className="text-xs text-muted-foreground">
                      Applied automatically by the pipeline.
                    </div>
                  </FilterGroup>

                  <FilterGroup title="Setup hits">
                    <div className="rounded-xl border border-outline/8 bg-card p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{UI_TERMS.setupHits}</span>
                        {setupStyles.length > 0 && (
                          <button
                            type="button"
                            onClick={() => updateSetupQuery({ styles: [] })}
                            className="text-xs font-semibold text-muted-foreground hover:text-primary"
                          >
                            Clear
                          </button>
                        )}
                      </div>

                      <div className="mt-2 flex flex-col gap-2">
                        <label className="flex items-center gap-2 text-xs text-muted-foreground">
                          <input
                            type="checkbox"
                            checked={hasSetupOnly}
                            onChange={(e) => updateHasSetupOnly(e.target.checked)}
                          />
                          Only show stocks with a setup-hit streak
                        </label>

                        <div className="inline-flex rounded-md border bg-muted/40 p-1 text-xs font-medium">
                          {(['both', 'bullish', 'bearish'] as const).map((b) => (
                            <button
                              key={b}
                              type="button"
                              onClick={() => updateSetupQuery({ bias: b })}
                              className={`rounded-sm px-3 py-1 transition ${
                                setupBias === b ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
                              }`}
                              aria-pressed={setupBias === b}
                              disabled={setupStyles.length === 0}
                            >
                              {b === 'both' ? 'Both' : b === 'bullish' ? 'Bullish' : 'Bearish'}
                            </button>
                          ))}
                        </div>

                        <label className="flex items-center gap-2 text-xs text-muted-foreground">
                          <input
                            type="checkbox"
                            checked={setupLogic === 'all'}
                            onChange={(e) => updateSetupQuery({ logic: e.target.checked ? 'all' : 'any' })}
                            disabled={setupStyles.length === 0}
                          />
                          Match all selected setup hits
                        </label>

                        <div className="flex flex-wrap gap-2">
                          {setupOptions.map((opt) => {
                            const selected = setupStyles.includes(opt.slug)
                            return (
                              <button
                                key={opt.slug}
                                type="button"
                                aria-pressed={selected}
                                onClick={() => {
                                  const next = selected
                                    ? setupStyles.filter((s) => s !== opt.slug)
                                    : [...setupStyles, opt.slug]
                                  const ordered = setupOptions.map((o) => o.slug).filter((s) => next.includes(s))
                                  updateSetupQuery({ styles: ordered })
                                }}
                                className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                                  selected
                                    ? 'border-primary bg-primary text-primary-foreground'
                                    : 'border-outline/10 bg-card text-muted-foreground hover:border-outline/16 hover:text-foreground'
                                }`}
                              >
                                {opt.label}
                              </button>
                            )
                          })}
                        </div>

                        <p className="text-[11px] text-muted-foreground">
                          Requires a {setupStreakDays}-day streak (setup hits: ≥1 hit in last {setupWindowDays} days).
                        </p>
                      </div>
                    </div>
                  </FilterGroup>

                  <FilterGroup title="Sentiment coverage">
                    <div className="text-xs text-muted-foreground">
                      All coverage levels included.
                    </div>
                  </FilterGroup>
                </FilterSidebar>
              </div>
            </CardContent>
          </Card>
          </aside>

          <main className="mt-6 space-y-6 lg:mt-0">
            <Card ref={resultsTopRef} id="rankings-results-top" className="border-outline/8">
              <CardHeader className="relative z-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                  <CardTitle>Rankings</CardTitle>
                  {gradesError ? (
                    <InlineError message="Couldn't load rankings." onRetry={() => void refetchGrades()} />
                  ) : (
                    !gradesLoading && (
                      <p className="text-sm text-muted-foreground">
                        Showing {displayStocks.length} of {totalCount} results
                        {countDelta ? (
                          <span className="ml-2 inline-flex items-center">
                            <Badge variant="secondary" className="text-[11px]">
                              {countDelta}
                            </Badge>
                          </span>
                        ) : null}
                      </p>
                    )
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="inline-flex items-center rounded-full border border-outline/10 bg-card p-1" aria-label="Rankings view mode">
                    <button
                      type="button"
                      className={cn(
                        'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
                        rankingsView === 'compact'
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground',
                      )}
                      onClick={() => setRankingsView('compact')}
                      aria-pressed={rankingsView === 'compact'}
                    >
                      <Table2Icon className="h-4 w-4" aria-hidden />
                      Compact
                    </button>
                    <button
                      type="button"
                      className={cn(
                        'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
                        rankingsView === 'cards'
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground',
                      )}
                      onClick={() => setRankingsView('cards')}
                      aria-pressed={rankingsView === 'cards'}
                    >
                      <LayoutGridIcon className="h-4 w-4" aria-hidden />
                      Cards
                    </button>
                  </div>
                  {!isMobile ? (
                    <DensityToggle value={density} onChange={setDensity} compactLabels />
                  ) : null}
                  {!isMobile && rankingsView === 'compact' ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-full px-3 text-xs"
                      onClick={() => setShowSparklines((prev) => !prev)}
                    >
                      {showSparklines ? 'Sparklines on' : 'Sparklines off'}
                    </Button>
                  ) : null}
                  <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Sort</span>
                  <select
                    value={sortBy}
                    onChange={(e) => {
                      const next = e.target.value as SortBy
                      setCurrentPage(1)
                      setSortBy(next)
                      setSortOrder(next === 'symbol' ? 'asc' : 'desc')
                    }}
                    className="h-8 rounded-md border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring sm:text-sm"
                  >
                    <option value="grade">Grade</option>
                    <option value="momentum">Momentum</option>
                    <option value="value">Value</option>
                    <option value="sentiment">Sentiment</option>
                    <option value="symbol">Symbol</option>
                  </select>
                  <button
                    className="rounded-md border px-2 py-1 text-xs hover:bg-accent"
                    title="Toggle sort order"
                    onClick={() => {
                      setCurrentPage(1)
                      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
                    }}
                  >
                    {sortOrder === 'asc' ? 'Asc ↑' : 'Desc ↓'}
                  </button>
                  {totalPages > 1 ? (
                    <>
                      <button
                        className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                        disabled={currentPage <= 1}
                        onClick={() => {
                          const next = Math.max(1, currentPage - 1)
                          setCurrentPage(next)
                          replaceRankingsUrl({ page: next })
                        }}
                      >
                        Prev
                      </button>
                      <span className="text-xs sm:text-sm">Page {currentPage} / {totalPages}</span>
                      <button
                        className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                        disabled={currentPage >= totalPages}
                        onClick={() => {
                          const next = Math.min(totalPages, currentPage + 1)
                          setCurrentPage(next)
                          replaceRankingsUrl({ page: next })
                        }}
                      >
                        Next
                      </button>
                    </>
                  ) : null}
                </div>
            </CardHeader>
            <CardContent className="relative z-10">
              {gradesLoading || gradesError || displayStocks.length === 0 ? (
                <DataStateWrapper
                  status={gradesLoading ? 'loading' : gradesError ? 'error' : 'empty'}
                  context="rankings"
                  loadingLabel="Loading Rankings…"
                  title={gradesError ? 'Data temporarily unavailable' : 'No results'}
                  message={
                    gradesError
                      ? gradesErrorMessage || 'Failed to load rankings.'
                      : hasActiveFilters
                        ? 'No stocks matched your filters.'
                        : 'No rankings are available yet.'
                  }
                  lastUpdated={lastUpdatedLabel}
                  filters={activeFilterChips.map((chip) => ({
                    key: chip.key,
                    label: chip.label,
                    onRemove: chip.onRemove
                      ? () => {
                          chip.onRemove?.()
                          setCurrentPage(1)
                        }
                      : undefined,
                  }))}
                  onClearFilters={hasActiveFilters ? resetToDefault : undefined}
                  clearFiltersLabel="Reset filters"
                  tips={
                    hasActiveFilters
                      ? ['Clear a grade or sector filter to widen the universe.', 'Try searching by ticker symbol.']
                      : ['Check back after the next pipeline refresh.', 'Try again in a few minutes.']
                  }
                  onRetry={gradesError ? () => void refetchGrades() : undefined}
                  error={gradesErrorRaw}
                />
              ) : (
                <div className="space-y-3">
                  {rankingsView === 'compact' ? (
                    <RankingsCompactTable
                      stocks={displayStocks}
                      aiPreview={grades?.ai_preview}
                      setupBySymbol={setupBySymbol}
                      density={effectiveDensity}
                      showSparklines={showSparklines && !isMobile}
                      sparklinesBySymbol={sparklineMap ?? {}}
                      onOpenStock={(symbol, rowId) => {
                        writeSessionStorageItem('rankalpha.focusReturnId', rowId)
                        openStock(symbol)
                      }}
                    />
                  ) : (
                    displayStocks.map((stock) => {
                      const setup = setupBySymbol[stock.symbol]
                      const hasWarning = !!setup && (stock.overall_grade === 'A' || stock.overall_grade === 'B') && setup.net_bias === 'bearish'
                      const contribRows = buildContributionRows(modelWeights, {
                        momentum: stock.momentum_score,
                        value: stock.value_score,
                        sentiment: stock.sentiment_score,
                      })
                      return (
                        <ClickableCard
                          key={`${stock.symbol}-${stock.date}`}
                          id={`rankings-row-${stock.symbol}`}
                          onActivate={() => {
                            writeSessionStorageItem('rankalpha.focusReturnId', `rankings-row-${stock.symbol}`)
                            openStock(stock.symbol)
                          }}
                          className={cn(
                            'group flex w-full flex-col rounded-2xl border bg-secondary/15 text-left shadow-sm sm:flex-row sm:items-start sm:justify-between',
                            isDense ? 'gap-3 p-3' : 'gap-4 p-4',
                            hasWarning
                              ? 'border-status-warning/25'
                              : 'border-outline/8'
                          )}
                          aria-label={`Open details for ${stock.symbol}`}
                        >
                          <div className={cn('flex flex-1 items-start', isDense ? 'gap-2 sm:gap-3' : 'gap-3 sm:gap-4')}>
                            <div className="mt-1 flex w-8 shrink-0 justify-center">
                              <CompareCheckbox symbol={stock.symbol} tooltipVariant="compact" />
                            </div>

                            <div className={cn('flex flex-1 flex-col sm:flex-row sm:items-start', isDense ? 'gap-2 sm:gap-3' : 'gap-3 sm:gap-4')}>
                              <div className="flex items-center gap-2">
                                <span className={cn('font-semibold', isDense ? 'text-base' : 'text-lg')}>{stock.symbol}</span>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <button
                                    type="button"
                                    className="inline-flex items-center gap-2"
                                    onClick={(event) => {
                                      event.preventDefault()
                                      event.stopPropagation()
                                    }}
                                    aria-label={`Why is ${stock.symbol} graded ${stock.overall_grade}`}
                                  >
                                    <Badge className={cn(getGradeBadgeColor(stock.overall_grade), 'px-3 py-1 text-sm')}>{stock.overall_grade}</Badge>
                                    <span className="text-xs font-semibold text-muted-foreground underline decoration-dotted decoration-outline/30 underline-offset-2 transition hover:text-foreground hover:decoration-outline/50">
                                      Why
                                    </span>
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent className="max-w-sm px-3 py-2 text-xs leading-relaxed">
                                  <div className="space-y-2">
                                    <div className="font-semibold text-foreground">Why this grade</div>
                                    <div className="text-muted-foreground">{stock.grade_explanation || 'No explanation provided.'}</div>
                                    {contribRows.length ? (
                                      <div className="space-y-2 pt-1">
                                        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Factor contributions</div>
                                        <div className="space-y-1">
                                          {contribRows.map((r) => (
                                            <div key={r.key} className="space-y-1">
                                              <div className="flex items-center justify-between text-[11px]">
                                                <span className="font-semibold text-foreground">{r.key}</span>
                                                <span className="text-muted-foreground">{Math.round(r.weight * 100)}%</span>
                                              </div>
                                              <div className="h-1.5 w-full rounded-full bg-secondary/30">
                                                <div
                                                  className="h-1.5 rounded-full bg-primary/70"
                                                  style={{ width: `${Math.max(8, Math.round(r.pct * 100))}%` }}
                                                />
                                              </div>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    ) : null}
                                  </div>
                                </TooltipContent>
                              </Tooltip>
                              {hasWarning && (
                                <Badge variant="warning" className="gap-1 px-2 py-0.5 text-[11px]">
                                  <AlertTriangleIcon className="h-3.5 w-3.5" />
                                  Net bearish · {setup.net_strength}
                                </Badge>
                              )}
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className={cn('truncate text-muted-foreground', isDense ? 'text-xs' : 'text-sm')}>{stock.company_name}</p>
                              <AiPreviewChips preview={grades?.ai_preview?.[stock.symbol]} />
                              <SetupInline symbol={stock.symbol} summary={setup} />
                            </div>
                          </div>
                          </div>
                          <div className="flex w-full flex-wrap items-center justify-start gap-2 text-sm sm:w-auto sm:justify-end sm:gap-2.5">
                            <Metric dense={isDense} label="Momentum" value={formatScore(stock.momentum_score)} />
                            <Metric dense={isDense} label="Value" value={formatScore(stock.value_score)} />
                            <Metric dense={isDense} label="Sentiment" value={formatScore(stock.sentiment_score)} />
                          </div>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation()
                                  writeSessionStorageItem('rankalpha.focusReturnId', `rankings-row-${stock.symbol}`)
                                  openStock(stock.symbol)
                                }}
                                className="inline-flex h-8 w-8 self-end items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background sm:self-center"
                                aria-label={`Open details for ${stock.symbol}`}
                              >
                                <ExternalLinkIcon className="h-4 w-4" aria-hidden="true" />
                              </button>
                            </TooltipTrigger>
                            <TooltipContent className="px-2 py-1 text-xs">Open ticker details</TooltipContent>
                          </Tooltip>
                        </ClickableCard>
                      )
                    })
                  )}
                </div>
              )}

              {totalPages > 1 && (
                <div className="mt-6 flex flex-wrap items-center justify-end gap-2 border-t border-border/60 pt-6 text-sm">
                  <button
                    className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                    disabled={currentPage <= 1}
                    onClick={() => {
                      const next = Math.max(1, currentPage - 1)
                      setCurrentPage(next)
                      replaceRankingsUrl({ page: next })
                    }}
                  >
                    Prev
                  </button>
                  <span className="text-xs sm:text-sm">Page {currentPage} / {totalPages}</span>
                  <button
                    className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                    disabled={currentPage >= totalPages}
                    onClick={() => {
                      const next = Math.min(totalPages, currentPage + 1)
                      setCurrentPage(next)
                      replaceRankingsUrl({ page: next })
                    }}
                  >
                    Next
                  </button>
                </div>
              )}
            </CardContent>
          </Card>
        </main>
      </div>
    </div>
  )
}

function RankingsCompactTable({
  stocks,
  aiPreview,
  setupBySymbol,
  density,
  showSparklines,
  sparklinesBySymbol,
  onOpenStock,
}: {
  stocks: StockGradeItem[]
  aiPreview?: Record<string, AiPreview> | undefined
  setupBySymbol: Record<string, SetupSummaryItem>
  density: 'comfortable' | 'dense'
  showSparklines: boolean
  sparklinesBySymbol: Record<string, number[]>
  onOpenStock: (symbol: string, rowId: string) => void
}) {
  const compare = useCompare()
  const isDense = density === 'dense'
  const cellPad = isDense ? 'px-2 py-2' : 'px-3 py-3'
  const headerPad = isDense ? 'px-2 py-1.5' : 'px-3 py-2'

  return (
    <div className="overflow-x-auto rounded-2xl border border-outline/10 bg-card">
      <DataTable className={cn('data-table--sticky min-w-[980px]', isDense ? 'text-[11px]' : 'text-sm')}>
        <thead>
          <tr className={cn('border-b border-outline/10 text-left font-semibold uppercase tracking-wide text-muted-foreground', isDense ? 'text-[10px]' : 'text-xs')}>
            <th className={cn('sticky left-0 z-20 w-10 bg-card', headerPad)}>
              <span className="sr-only">Compare</span>
            </th>
            <th className={cn('sticky left-10 z-20 bg-card border-r border-outline/10', headerPad)}>Ticker</th>
            <th className={headerPad}>
              <ColumnHeaderTooltip label="Grade" tooltipKey="rankings.grade" />
            </th>
            <th className={headerPad}>
              <ColumnHeaderTooltip label="M" tooltipKey="rankings.momentumScore" />
            </th>
            <th className={headerPad}>
              <ColumnHeaderTooltip label="V" tooltipKey="rankings.valueScore" />
            </th>
            <th className={headerPad}>
              <ColumnHeaderTooltip label="S" tooltipKey="rankings.sentimentScore" />
            </th>
            <th className={headerPad}>
              <ColumnHeaderTooltip label={formatSetupHitsLabel(SETUP_WINDOW_DAYS)} tooltipKey="rankings.setupHits" />
            </th>
            <th className={headerPad}>
              <ColumnHeaderTooltip label={UI_TERMS.aiTargetBase} tooltipKey="rankings.aiTargetBase" />
            </th>
            {showSparklines ? (
              <th className={headerPad}>
                <span className="text-xs">Trend</span>
              </th>
            ) : null}
            <th className={headerPad}>
              <ColumnHeaderTooltip label="Updated" tooltipKey="global.asOf" />
            </th>
            <th className={cn('w-8 text-right', headerPad)}>
              <span className="sr-only">Open</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((stock) => {
            const symbol = (stock.symbol || '').trim().toUpperCase()
            const rowId = `rankings-row-${symbol}`
            const preview = symbol ? aiPreview?.[symbol] : undefined
            const basePt = preview?.base_price_target
            const showPt = typeof basePt === 'number' && Number.isFinite(basePt)
            return (
              <ClickableTableRow
                key={`${stock.symbol}-${stock.date}`}
                id={rowId}
                aria-label={`Open details for ${symbol}`}
                onActivate={() => onOpenStock(symbol, rowId)}
                selected={compare.symbols.includes(symbol)}
                className={cn('group bg-card', isDense && 'text-[11px]')}
              >
                <CompareCheckboxCell symbol={symbol} cellClassName={cn('sticky left-0 z-10 bg-card', cellPad)} />
                <td className={cn('sticky left-10 z-10 bg-card align-middle border-r border-outline/10', cellPad)}>
                  <div className="min-w-0">
                    <div className={cn('font-semibold text-foreground', isDense ? 'text-xs' : 'text-sm')}>{symbol}</div>
                    <div className={cn('max-w-[26rem] truncate text-muted-foreground', isDense ? 'text-[10px]' : 'text-xs')}>
                      {stock.company_name || '-'}
                    </div>
                  </div>
                </td>
                <td className={cn(cellPad, 'align-middle')}>
                  <Badge className={cn(getGradeBadgeColor(stock.overall_grade), 'px-2 py-0.5 text-xs font-semibold')}>
                    {stock.overall_grade || '-'}
                  </Badge>
                </td>
                <td className={cn(cellPad, 'align-middle font-semibold tabular-nums text-foreground')}>{formatScore(stock.momentum_score)}</td>
                <td className={cn(cellPad, 'align-middle font-semibold tabular-nums text-foreground')}>{formatScore(stock.value_score)}</td>
                <td className={cn(cellPad, 'align-middle font-semibold tabular-nums text-foreground')}>{formatScore(stock.sentiment_score)}</td>
                <td className={cn(cellPad, 'align-middle')}>
                  <RankingsCompactSetupCell symbol={symbol} summary={setupBySymbol[symbol]} />
                </td>
                <td className={cn(cellPad, 'align-middle font-semibold tabular-nums text-foreground')}>
                  {showPt ? `$${formatNumberValue(basePt, 0)}` : <span className="text-muted-foreground">-</span>}
                </td>
                {showSparklines ? (
                  <td className={cn(cellPad, 'align-middle')}>
                    {sparklinesBySymbol[symbol]?.length ? (
                      <MiniSparkline values={sparklinesBySymbol[symbol]} />
                    ) : (
                      <span className="text-xs text-muted-foreground">-</span>
                    )}
                  </td>
                ) : null}
                <td className={cn(cellPad, 'align-middle text-xs text-muted-foreground')}>
                  {stock.date ? formatEasternDate(stock.date) : '-'}
                </td>
                <td className={cn(cellPad, 'align-middle text-right')}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation()
                          onOpenStock(symbol, rowId)
                        }}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        aria-label={`Open details for ${symbol}`}
                      >
                        <ExternalLinkIcon className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent className="px-2 py-1 text-xs">Open ticker details</TooltipContent>
                  </Tooltip>
                </td>
              </ClickableTableRow>
            )
          })}
        </tbody>
      </DataTable>
      <DataFooter
        source="Internal model"
        links={[{ label: 'Methodology', href: '/about/factors' }]}
        className="px-3 pb-3"
      />
    </div>
  )
}

function RankingsCompactSetupCell({ symbol, summary }: { symbol: string; summary?: SetupSummaryItem }) {
  if (!summary) return <span className="text-xs text-muted-foreground">-</span>

  const primary = summary.net_bias === 'bearish' ? summary.bearish : summary.bullish
  const secondary = summary.net_bias === 'bearish' ? summary.bullish : summary.bearish
  const combined = [...primary, ...secondary]
  const shown = combined.slice(0, 2)

  const totalCount =
    (summary.bullish?.length ?? 0) +
    (summary.bearish?.length ?? 0) +
    (summary.bullish_extra_count ?? 0) +
    (summary.bearish_extra_count ?? 0)
  const remaining = Math.max(0, totalCount - shown.length)

  const allLabels = [
    ...(summary.bullish ?? []).map((c) => formatSetupTag(c.label, c.streak_days)),
    ...(summary.bearish ?? []).map((c) => formatSetupTag(c.label, c.streak_days)),
  ].filter(Boolean)

  return (
    <div className="flex flex-wrap items-center gap-2">
      {shown.length ? (
        shown.map((chip) => {
          const tone: BadgeProps['variant'] = chip.bias === 'bearish' ? 'danger' : 'success'
          const label = formatSetupTag(chip.label, chip.streak_days)
          const chipNode = chip.interactive && chip.slug ? (
            <Link
              href={`/screener?symbol=${encodeURIComponent(symbol)}&focus_slug=${encodeURIComponent(chip.slug)}`}
              onClick={(e) => e.stopPropagation()}
              className={cn(badgeVariants({ variant: tone, interactive: true }), 'text-[11px]')}
            >
              {label}
            </Link>
          ) : (
            <span className={cn(badgeVariants({ variant: tone, interactive: false }), 'text-[11px]')}>
              {label}
            </span>
          )
          return (
            <TooltipCopy key={`${chip.bias}-${chip.slug ?? chip.label}-${chip.label}`} tooltipKey="rankings.setupTag">
              {chipNode}
            </TooltipCopy>
          )
        })
      ) : (
        <span className="text-xs text-muted-foreground">-</span>
      )}

      {remaining > 0 ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="rounded-full border border-outline/10 bg-card px-2 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              aria-label={`Show ${remaining} more setup hit tags`}
            >
              +{remaining}
            </button>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs px-3 py-2 text-xs leading-relaxed">
            <div className="space-y-1.5">
              <div className="font-semibold text-foreground">All setup hit tags</div>
              <div className="text-muted-foreground">{allLabels.join(', ') || '-'}</div>
            </div>
          </TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  )
}

function getGradeBadgeColor(grade: string) {
  switch (grade) {
    case 'A':
      return 'bg-status-success-soft text-status-success'
    case 'B':
      return 'bg-status-success/10 text-status-success'
    case 'C':
      return 'bg-status-warning/10 text-status-warning-foreground'
    case 'D':
      return 'bg-status-danger/10 text-status-danger'
    case 'F':
      return 'bg-status-danger-soft text-status-danger'
    default:
      return 'bg-neutralsoft text-foreground'
  }
}

function Metric({ label, value, dense = false }: { label: string; value: string; dense?: boolean }) {
  return (
    <div className={cn('flex min-w-[92px] flex-col gap-0.5', dense && 'min-w-[80px]')}>
      <span className={cn('font-semibold uppercase tracking-wide text-muted-foreground', dense ? 'text-[10px]' : 'text-[11px]')}>
        {label}
      </span>
      <span className={cn('tabular-nums font-semibold text-foreground', dense ? 'text-sm' : 'text-base')}>
        {value}
      </span>
    </div>
  )
}

function SetupInline({ symbol, summary }: { symbol: string; summary?: SetupSummaryItem }) {
  if (!summary) return null

  const showNet = summary.net_bias !== 'neutral'
  const netLabel = summary.net_bias === 'bearish' ? 'Net Bearish' : 'Net Bullish'
  const netTone = summary.net_bias === 'bearish' ? 'danger' : 'success'

  return (
    <div className="mt-2 space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>{formatSetupHitsLabel(SETUP_WINDOW_DAYS)}</span>
        {showNet && (
          <Badge variant={netTone} className="px-2 py-0.5 text-[11px]">
            {netLabel} · {summary.net_strength}
          </Badge>
        )}
      </div>
      <SetupSideRow
        symbol={symbol}
        title="Bullish"
        chips={summary.bullish}
        extraCount={summary.bullish_extra_count}
        developing={summary.bullish_developing}
      />
      <SetupSideRow
        symbol={symbol}
        title="Bearish"
        chips={summary.bearish}
        extraCount={summary.bearish_extra_count}
        developing={summary.bearish_developing}
      />
    </div>
  )
}

function SetupSideRow({
  symbol,
  title,
  chips,
  extraCount,
  developing,
}: {
  symbol: string
  title: string
  chips: SetupChip[]
  extraCount: number
  developing: SetupDeveloping
}) {
  const tone: BadgeProps['variant'] = title === 'Bearish' ? 'danger' : 'success'
  const maxChips = 2
  const shown = chips.slice(0, maxChips)
  const remaining = Math.max(0, chips.length - shown.length) + Math.max(0, extraCount || 0)

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {title === 'Bearish' ? (
            <ArrowDownIcon className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <ArrowUpIcon className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {title}
        </span>
        {shown.length > 0 ? (
          <>
            {shown.map((chip) => {
              const label = formatSetupTag(chip.label, chip.streak_days)
              const chipNode = chip.interactive && chip.slug ? (
                <Link
                  href={`/screener?symbol=${encodeURIComponent(symbol)}&focus_slug=${encodeURIComponent(chip.slug)}`}
                  onClick={(e) => e.stopPropagation()}
                  className={cn(badgeVariants({ variant: tone, interactive: true }), 'text-[11px]')}
                >
                  {label}
                </Link>
              ) : (
                <span className={cn(badgeVariants({ variant: tone, interactive: false }), 'text-[11px]')}>
                  {label}
                </span>
              )
              return (
                <TooltipCopy key={`${chip.bias}-${chip.slug ?? chip.label}-${chip.label}`} tooltipKey="rankings.setupTag">
                  {chipNode}
                </TooltipCopy>
              )
            })}
            {remaining > 0 ? <span className="text-[11px] font-semibold text-muted-foreground">+{remaining}</span> : null}
          </>
        ) : (
        <span className="text-[11px] text-muted-foreground">
          {developing.streak_days > 0 && developing.labels.length > 0
            ? `Developing ${developing.streak_days}d`
            : '-'}
        </span>
      )}
      </div>
    )
}

function AiPreviewChips({ preview }: { preview?: { events_count?: number; base_price_target?: number; has_thesis?: boolean } }) {
  if (!preview) return null
  const eventsCount = preview.events_count || 0
  const hasThesis = !!preview.has_thesis
  const basePT = preview.base_price_target
  if (!hasThesis && !eventsCount && (basePT === undefined || basePT === null)) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5">
      {/* {hasThesis && (
        <Badge variant="secondary" className="text-xs">Thesis</Badge>
      )} */}
      {typeof basePT === 'number' && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline" className="text-xs">
              {UI_TERMS.aiTarget} ${Number(basePT).toFixed(0)}
            </Badge>
          </TooltipTrigger>
          <TooltipContent className="px-3 py-2">
            <TooltipCopyContent tooltipKey="rankings.aiTargetBase" />
          </TooltipContent>
        </Tooltip>
      )}
      {/* {eventsCount > 0 && (
        <Badge variant="outline" className="text-xs">Events {eventsCount}</Badge>
      )} */}
    </div>
  )
}
