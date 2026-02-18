'use client'

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, AiPreview, ScreenerBreadthItem, ScreenerBreadthFlowItem, ScreenerChangeItem, ScreenerChangeType, ScreenerConsensusItem } from '@/lib/api'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { MultiSelect } from '@/components/filters/multi-select'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/page-header'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { Skeleton } from '@/components/ui/skeleton'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { formatEasternDate } from '@/lib/date'
import { ArrowDownIcon, ArrowUpIcon, ChevronDownIcon, CopyIcon, DownloadIcon, ExternalLinkIcon, FilterIcon, LayoutGridIcon, PinIcon, Table2Icon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { FIVE_MIN_MS, TWO_MIN_MS } from '@/lib/time'
import { formatNumberValue, formatPct } from '@/lib/format'
import { UI_TERMS } from '@/lib/ui_terms'
import { formatSigned } from '@/lib/nowcast-utils'
import { readLocalStorageJson, removeLocalStorageItem, writeLocalStorageJson, writeSessionStorageItem } from '@/lib/storage'
import { Button } from '@/components/ui/button'
import { DataTable } from '@/components/ui/data-table'
import { ClickableCard } from '@/components/interaction/clickable_card'
import { ClickableTableRow } from '@/components/interaction/clickable_table_row'
import { InfoTooltipButton } from '@/components/info_tooltip_button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import { useCompare } from '@/components/compare/compare_context'
import { CompareCheckbox } from '@/components/compare/compare_checkbox'
import { CompareCheckboxCell } from '@/components/compare/compare_checkbox_cell'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCountDeltaBadge } from '@/lib/use_count_delta'
import { useScreenerMethodology } from '@/components/screeners/screener_methodology_context'
import { ScreenerTabs } from '@/components/screener/screener_tabs'
import { TooltipCopy, TooltipCopyButton, TooltipCopyContent } from '@/components/tooltip_copy'
import { SavedViewsDialog } from '@/components/saved-views/saved_views_dialog'
import { SavedViewsButton } from '@/components/saved-views/saved_views_button'
import { useSavedViewsDrawer, useSavedViewsLinks } from '@/components/saved-views/use_saved_views_drawer'
import { useShareCurrentView } from '@/components/saved-views/use_share_current_view'
import { useScreenerSavedView } from '@/features/explore/use_screener_saved_view'
import { DataStateWrapper } from '@/components/data-state-wrapper'
import { DataFooter } from '@/components/data-footer'
import { DataFreshness } from '@/components/data/data-freshness'
import { DensityToggle } from '@/components/density-toggle'
import { MiniSparkline } from '@/components/charts/mini-sparkline'
import { InlineError } from '@/components/ui/inline-error'
import { ColumnHeaderTooltip } from '@/components/column-header-tooltip'
import { ActiveFilterChips } from '@/components/filters/ActiveFilterChips'
import { FilterGroup, FilterSidebar } from '@/components/filters/FilterSidebar'
import { useFilterRailState } from '@/components/filters/use_filter_rail_state'
import { ResultRowDetails } from '@/components/screener/ResultRowDetails'
import { rememberTickerOrigin } from '@/lib/ticker_nav'
import { useMediaQuery } from '@/lib/use_media_query'
import { useUiDensity } from '@/lib/ui_density'
import { fetchSparklinePriceMap } from '@/lib/sparklines'

type ScreenerConsensusViewProps = {
  persistQueryKeys?: string[]
  initialStyles?: string[]
}

function MetricTile({ label, value, dense = false }: { label: string; value: ReactNode; dense?: boolean }) {
  return (
    <div className={cn('rounded-xl border border-outline/10 bg-secondary/10', dense ? 'p-1.5' : 'p-2')}>
      <div className={cn('font-semibold uppercase tracking-wide text-muted-foreground', dense ? 'text-[10px]' : 'text-[11px]')}>
        {label}
      </div>
      <div className={cn('mt-0.5 font-semibold text-foreground tabular-nums', dense ? 'text-[13px]' : 'text-sm')}>
        {value}
      </div>
    </div>
  )
}

const DEFAULT_PERSIST_KEYS: string[] = []
const DEFAULT_INITIAL_STYLES: string[] = []
const DEFAULT_MOVEMENT_WINDOW_DAYS = 3

type ScreenerPersistedFilters = {
  styles?: string[]
  sources?: string[]
  styleLogic?: 'any' | 'all'
  sourceLogic?: 'any' | 'all'
  appearancesMin?: number
  stylesMin?: number
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
  bias?: 'all' | 'bullish' | 'bearish'
}

const SCREENER_FILTERS_STORAGE_KEY = 'rankalpha.screener.filters.v1'
const SCREENER_RESULTS_COLUMNS_STORAGE_KEY = 'rankalpha.screener.results.columns.v1'
const SCREENER_RESULTS_LAYOUTS_KEY = 'rankalpha.screener.results.layouts.v1'
const SCREENER_SAVED_VIEWS_KEY = 'rankalpha.screener.saved_views.v1'
const SCREENER_TAB_STORAGE_KEY = 'rankalpha.screener.tab.v1'
const SCREENER_RESULTS_VIEW_KEY = 'rankalpha.screener.results.view.v1'
const SCREENER_SPARKS_STORAGE_KEY = 'rankalpha.screener.sparklines.v1'
const SCREENER_BREADTH_PIN_KEY = 'rankalpha.screener.breadth.pins.v1'
const SCREENER_FILTERS_COLLAPSED_KEY = 'rankalpha.screener.filtersCollapsed.v1'

type TriageFocus = 'entered' | 'reentered' | 'dropped'

type ResultsColumnKey =
  | 'company'
  | 'ai'
  | 'rank_best'
  | 'appearances'
  | 'styles_distinct'
  | 'sources_distinct'
  | 'min_style_rank_pct'
  | 'consensus_score'
  | 'primary'

type ResultsColumnLayout = { name: string; columns: ResultsColumnKey[] }

const RESULTS_COLUMN_KEYS: ResultsColumnKey[] = [
  'company',
  'ai',
  'rank_best',
  'appearances',
  'styles_distinct',
  'sources_distinct',
  'min_style_rank_pct',
  'consensus_score',
  'primary',
]
const RESULTS_COLUMN_LABELS: Record<ResultsColumnKey, string> = {
  company: 'Company',
  ai: 'AI Snapshot',
  rank_best: 'Best Rank',
  appearances: 'Appearances',
  styles_distinct: 'Styles',
  sources_distinct: 'Sources',
  min_style_rank_pct: 'Best %ile',
  consensus_score: 'Consensus',
  primary: 'Primary',
}

const DEFAULT_RESULTS_COLUMNS: ResultsColumnKey[] = [...RESULTS_COLUMN_KEYS]
const RESULTS_COLUMNS_PARAM_KEY = 'cols'
const RESULTS_VIEW_PARAM_KEY = 'view'

function parseResultsViewParam(raw?: string | null): 'table' | 'cards' | null {
  const v = (raw || '').trim().toLowerCase()
  if (v === 'table' || v === 'cards') return v
  return null
}

function parseResultsColumnsParam(raw?: string | null): ResultsColumnKey[] | null {
  const cleaned = (raw || '')
    .split(',')
    .map((v) => v.trim())
    .filter((v): v is ResultsColumnKey => RESULTS_COLUMN_KEYS.includes(v as ResultsColumnKey))
  if (!cleaned.length) return null
  const seen = new Set<ResultsColumnKey>()
  const ordered: ResultsColumnKey[] = []
  cleaned.forEach((key) => {
    if (seen.has(key)) return
    seen.add(key)
    ordered.push(key)
  })
  return ordered.length ? ordered : null
}

function areColumnsEqual(a: ResultsColumnKey[], b: ResultsColumnKey[]) {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false
  }
  return true
}

// Bias and signed metrics are computed server-side by the API.

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(handle)
  }, [value, delayMs])
  return debounced
}

export function ScreenerConsensusView({
  persistQueryKeys = DEFAULT_PERSIST_KEYS,
  initialStyles = DEFAULT_INITIAL_STYLES,
}: ScreenerConsensusViewProps = {}) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const { toast } = useToast()
  const searchParamsString = searchParams?.toString() ?? ''
  const queryClient = useQueryClient()
  const persistKeySignature = useMemo(() => persistQueryKeys.join('|'), [persistQueryKeys])
  const persistKeys = useMemo(() => persistQueryKeys.slice(), [persistQueryKeys])
  const initializedRef = useRef(false)
  const normalizedInitialStyles = initialStyles.map((s) => (s || '').trim()).filter(Boolean)
  const [searchQuery, setSearchQuery] = useState('')
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 250)
  const urlSearchQuery = debouncedSearchQuery.trim()
  const tickerCandidate = useMemo(() => {
    const raw = searchQuery.trim()
    if (!raw) return ''
    const upper = raw.toUpperCase()
    if (!/^[A-Z0-9.]+$/.test(upper)) return ''
    if (upper.length < 2 || upper.length > 6) return ''
    return upper
  }, [searchQuery])
  const symbolFilter = useMemo(() => {
    const raw = urlSearchQuery.trim()
    if (!raw) return ''
    const upper = raw.toUpperCase()
    if (!/^[A-Z0-9.]+$/.test(upper)) return ''
    if (upper.length < 1 || upper.length > 6) return ''
    return upper
  }, [urlSearchQuery])
  const [styles, setStyles] = useState<string[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [styleMatchAll, setStyleMatchAll] = useState(true)
  const [sourceMatchAll, setSourceMatchAll] = useState(true)
  const [appearancesMin, setAppearancesMin] = useState(0)
  const [stylesMin, setStylesMin] = useState(0)
  const [page, setPage] = useState(1)
  const [bias, setBias] = useState<'all' | 'bullish' | 'bearish'>('all')
  type SortBy = 'consensus_score' | 'appearances' | 'styles_distinct' | 'sources_distinct' | 'rank_best' | 'min_style_rank_pct' | 'symbol'
  type SortOrder = 'asc' | 'desc'
  const [sortBy, setSortBy] = useState<SortBy>('consensus_score')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')
  const pageSize = 25
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const { collapsed: filtersCollapsed, setCollapsed: setFiltersCollapsed } = useFilterRailState(
    SCREENER_FILTERS_COLLAPSED_KEY,
  )
  const [resultsView, setResultsView] = useState<'table' | 'cards'>('table')
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({})
  const resultsTopRef = useRef<HTMLElement | null>(null)
  const isMobile = useMediaQuery(
    '(max-width: 767px)',
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 767px)').matches : false
  )
  const { density, setDensity } = useUiDensity('comfortable')
  const effectiveDensity = isMobile ? 'comfortable' : density
  const isDense = effectiveDensity === 'dense'
  const [showSparklines, setShowSparklines] = useState(false)
  const hasInitializedSparks = useRef(false)
  const hasAppliedResultsView = useRef(false)
  const hasAppliedColumns = useRef(false)
  const resultsViewParam = useMemo(
    () => parseResultsViewParam(searchParams?.get(RESULTS_VIEW_PARAM_KEY)),
    [searchParams],
  )
  const resultsColumnsParam = useMemo(
    () => parseResultsColumnsParam(searchParams?.get(RESULTS_COLUMNS_PARAM_KEY)),
    [searchParams],
  )
  const { viewsOpen, openViews, onOpenChange } = useSavedViewsDrawer({
    pathname,
    fallbackPath: '/screener',
    searchParams,
    router,
  })
  const suspendUrlSyncRef = useRef(false)
  const stylesKey = useMemo(() => styles.join(','), [styles])

  useEffect(() => {
    if (hasInitializedSparks.current) return
    const persisted = readLocalStorageJson<{ v: 1; enabled: boolean }>(SCREENER_SPARKS_STORAGE_KEY)
    const initial = typeof persisted?.enabled === 'boolean' ? persisted.enabled : false
    setShowSparklines(initial)
    hasInitializedSparks.current = true
  }, [])

  useEffect(() => {
    writeLocalStorageJson(SCREENER_SPARKS_STORAGE_KEY, { v: 1, enabled: showSparklines })
  }, [showSparklines])
  const sourcesKey = useMemo(() => sources.join(','), [sources])
  const positionSide = useMemo<'long' | 'short' | undefined>(
    () => (bias === 'bullish' ? 'long' : bias === 'bearish' ? 'short' : undefined),
    [bias]
  )

  const [resultsColumnsOpen, setResultsColumnsOpen] = useState(false)
  const [resultsColumns, setResultsColumns] = useState<ResultsColumnKey[]>(() => {
    const persisted = readLocalStorageJson<{ v: 1; visible: ResultsColumnKey[] }>(SCREENER_RESULTS_COLUMNS_STORAGE_KEY)
    if (!persisted || persisted.v !== 1 || !Array.isArray(persisted.visible)) return DEFAULT_RESULTS_COLUMNS
    const cleaned = persisted.visible.filter((k): k is ResultsColumnKey => RESULTS_COLUMN_KEYS.includes(k))
    return cleaned.length ? cleaned : DEFAULT_RESULTS_COLUMNS
  })
  const [resultsLayouts, setResultsLayouts] = useState<ResultsColumnLayout[]>(() => {
    const persisted = readLocalStorageJson<{ v: 1; layouts: ResultsColumnLayout[] }>(SCREENER_RESULTS_LAYOUTS_KEY)
    if (!persisted || persisted.v !== 1 || !Array.isArray(persisted.layouts)) return []
    return persisted.layouts
      .map((layout) => ({
        name: (layout?.name || '').toString().trim(),
        columns: Array.isArray(layout?.columns)
          ? layout.columns.filter((k): k is ResultsColumnKey => RESULTS_COLUMN_KEYS.includes(k))
          : [],
      }))
      .filter((layout) => layout.name && layout.columns.length)
  })
  const [layoutName, setLayoutName] = useState('')

  useEffect(() => {
    if (!resultsColumnsParam) {
      if (!hasAppliedColumns.current) {
        hasAppliedColumns.current = true
      }
      return
    }
    setResultsColumns((prev) => (areColumnsEqual(prev, resultsColumnsParam) ? prev : resultsColumnsParam))
    hasAppliedColumns.current = true
  }, [resultsColumnsParam])

  useEffect(() => {
    writeLocalStorageJson(SCREENER_RESULTS_COLUMNS_STORAGE_KEY, { v: 1, visible: resultsColumns })
  }, [resultsColumns])

  useEffect(() => {
    writeLocalStorageJson(SCREENER_RESULTS_LAYOUTS_KEY, { v: 1, layouts: resultsLayouts })
  }, [resultsLayouts])


  const isResultsColumnVisible = (key: ResultsColumnKey) => resultsColumns.includes(key)
  const hiddenResultsColumns = RESULTS_COLUMN_KEYS.filter((key) => !resultsColumns.includes(key))
  const resultsDetailsColSpan = 4 + resultsColumns.length
  const rowPad = isDense ? 'py-1 sm:py-1.5' : 'py-1.5 sm:py-2'
  const cellPad = isDense ? 'pr-2 sm:pr-3' : 'pr-3 sm:pr-4'
  const headerPad = isDense ? 'py-1' : 'py-2'
  const renderResultsHeader = (key: ResultsColumnKey) => {
    switch (key) {
      case 'company':
        return (
          <th key={key} className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 align-middle backdrop-blur', headerPad, cellPad)}>
            <ColumnHeaderTooltip label="Company" tooltipKey="screener.results.company" />
          </th>
        )
      case 'ai':
        return (
          <th key={key} className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 text-left align-middle backdrop-blur', headerPad, cellPad)}>
            <ColumnHeaderTooltip label="AI Snapshot" tooltipKey="screener.results.ai" />
          </th>
        )
      case 'rank_best':
        return (
          <SortableTh
            key={key}
            label="Best Rank"
            tooltip={<TooltipCopyContent tooltipKey="screener.results.bestRank" />}
            active={sortBy === 'rank_best'}
            order={sortOrder}
            onClick={() => handleHeaderSort('rank_best')}
            align="right"
            className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 backdrop-blur', headerPad, cellPad)}
          />
        )
      case 'appearances':
        return (
          <SortableTh
            key={key}
            label="Appear"
            tooltip={<TooltipCopyContent tooltipKey="screener.results.appearances" />}
            active={sortBy === 'appearances'}
            order={sortOrder}
            onClick={() => handleHeaderSort('appearances')}
            align="right"
            className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 backdrop-blur', headerPad, cellPad)}
          />
        )
      case 'styles_distinct':
        return (
          <SortableTh
            key={key}
            label="Styles"
            tooltip={<TooltipCopyContent tooltipKey="screener.results.styles" />}
            active={sortBy === 'styles_distinct'}
            order={sortOrder}
            onClick={() => handleHeaderSort('styles_distinct')}
            align="right"
            className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 backdrop-blur', headerPad, cellPad)}
          />
        )
      case 'sources_distinct':
        return (
          <SortableTh
            key={key}
            label="Sources"
            tooltip={<TooltipCopyContent tooltipKey="screener.results.sources" />}
            active={sortBy === 'sources_distinct'}
            order={sortOrder}
            onClick={() => handleHeaderSort('sources_distinct')}
            align="right"
            className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 backdrop-blur hidden xl:table-cell', headerPad, cellPad)}
          />
        )
      case 'min_style_rank_pct':
        return (
          <SortableTh
            key={key}
            label="Best %ile"
            tooltip={<TooltipCopyContent tooltipKey="screener.results.bestPercentile" />}
            active={sortBy === 'min_style_rank_pct'}
            order={sortOrder}
            onClick={() => handleHeaderSort('min_style_rank_pct')}
            align="right"
            className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 backdrop-blur hidden lg:table-cell', headerPad, cellPad)}
          />
        )
      case 'consensus_score':
        return (
          <SortableTh
            key={key}
            label="Consensus"
            tooltip={<TooltipCopyContent tooltipKey="screener.results.consensusScore" />}
            active={sortBy === 'consensus_score'}
            order={sortOrder}
            onClick={() => handleHeaderSort('consensus_score')}
            align="right"
            className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 backdrop-blur', headerPad, cellPad)}
          />
        )
      case 'primary':
        return (
          <th key={key} className={cn('sticky top-0 z-10 border-b border-border/60 bg-background/90 align-middle backdrop-blur hidden xl:table-cell', headerPad, cellPad)}>
            <div className="flex items-center gap-1">
              <span>Primary</span>
              <TooltipCopyButton
                tooltipKey="screener.results.primary"
                iconSize="h-3.5 w-3.5"
                buttonClassName="text-muted-foreground hover:text-foreground"
              />
            </div>
          </th>
        )
      default:
        return null
    }
  }

  const renderResultsCell = (key: ResultsColumnKey, row: ScreenerConsensusItem, preview?: AiPreview) => {
    switch (key) {
      case 'company':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'max-w-[10rem] truncate align-middle sm:max-w-[16rem]')} title={row.company_name || ''}>
            {row.company_name || '-'}
          </td>
        )
      case 'ai':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'text-left align-middle')}>
            {preview ? <AiPreviewChips preview={preview} /> : '-'}
          </td>
        )
      case 'rank_best':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'text-right align-middle tabular-nums')}>
            {formatNumberValue(row.rank_best ?? null, 0)}
          </td>
        )
      case 'appearances':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'text-right align-middle tabular-nums')}>
            {formatNumberValue(row.appearances ?? null, 1)}
          </td>
        )
      case 'styles_distinct':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'text-right align-middle tabular-nums')}>
            {formatNumberValue(row.styles_distinct ?? null, 1)}
          </td>
        )
      case 'sources_distinct':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'hidden xl:table-cell text-right align-middle tabular-nums')}>
            {formatNumberValue(row.sources_distinct ?? null, 1)}
          </td>
        )
      case 'min_style_rank_pct':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'hidden lg:table-cell text-right align-middle tabular-nums')}>
            {formatPct(row.min_style_rank_pct, 1)}
          </td>
        )
      case 'consensus_score':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'text-right align-middle tabular-nums font-semibold')}>
            {formatNumberValue(row.consensus_score ?? null, 0)}
          </td>
        )
      case 'primary':
        return (
          <td key={key} className={cn(rowPad, cellPad, 'hidden xl:table-cell align-middle text-xs text-muted-foreground')}>
            {row.primary_style || row.primary_source ? `Primary ${row.primary_style || '-'} / ${row.primary_source || '-'}` : '-'}
          </td>
        )
      default:
        return null
    }
  }
  const toggleResultsColumn = (key: ResultsColumnKey) => {
    setResultsColumns((prev) => {
      if (prev.includes(key)) {
        const next = prev.filter((k) => k !== key)
        return next.length ? next : prev
      }
      return [...prev, key]
    })
  }
  const moveResultsColumn = (key: ResultsColumnKey, direction: 'up' | 'down') => {
    setResultsColumns((prev) => {
      const idx = prev.indexOf(key)
      if (idx === -1) return prev
      const next = [...prev]
      const target = direction === 'up' ? idx - 1 : idx + 1
      if (target < 0 || target >= next.length) return prev
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return next
    })
  }
  const saveResultsLayout = () => {
    const name = layoutName.trim()
    if (!name) return
    setResultsLayouts((prev) => {
      const next = prev.filter((l) => l.name.toLowerCase() !== name.toLowerCase())
      return [...next, { name, columns: resultsColumns }]
    })
    setLayoutName('')
  }
  const applyResultsLayout = (layout: ResultsColumnLayout) => {
    if (layout?.columns?.length) setResultsColumns(layout.columns)
  }
  const removeResultsLayout = (name: string) => {
    setResultsLayouts((prev) => prev.filter((l) => l.name !== name))
  }

  // One-time: initialize state from URL
  useEffect(() => {
    if (initializedRef.current) return
    const sp = searchParams
    if (!sp) return

    const hasExplicitQuery =
      Boolean(sp.get('q')) ||
      Boolean(sp.get('symbol_filter')) ||
      Boolean(sp.get('styles')) ||
      Boolean(sp.get('sources')) ||
      Boolean(sp.get('style_logic')) ||
      Boolean(sp.get('source_logic')) ||
      Boolean(sp.get('appearances_min')) ||
      Boolean(sp.get('styles_min')) ||
      Boolean(sp.get('sort_by')) ||
      Boolean(sp.get('sort_order')) ||
      Boolean(sp.get('bias'))

    if (!hasExplicitQuery) {
      const persisted = readLocalStorageJson<ScreenerPersistedFilters>(SCREENER_FILTERS_STORAGE_KEY)
      if (persisted) {
        const st = Array.isArray(persisted.styles) ? persisted.styles.map((s) => (s || '').trim()).filter(Boolean) : []
        const so = Array.isArray(persisted.sources) ? persisted.sources.map((s) => (s || '').trim()).filter(Boolean) : []
        const sl = persisted.styleLogic === 'any' || persisted.styleLogic === 'all' ? persisted.styleLogic : null
        const sol = persisted.sourceLogic === 'any' || persisted.sourceLogic === 'all' ? persisted.sourceLogic : null
        const am = typeof persisted.appearancesMin === 'number' ? persisted.appearancesMin : 0
        const sm = typeof persisted.stylesMin === 'number' ? persisted.stylesMin : 0
        const sb = persisted.sortBy || ''
        const sox = persisted.sortOrder === 'asc' || persisted.sortOrder === 'desc' ? persisted.sortOrder : null
        const biasParam = persisted.bias && ['all', 'bullish', 'bearish'].includes(persisted.bias) ? persisted.bias : null

        if (st.length) setStyles(st)
        else if (normalizedInitialStyles.length) setStyles(normalizedInitialStyles)
        if (so.length) setSources(so)
        if (sl) setStyleMatchAll(sl === 'all')
        if (sol) setSourceMatchAll(sol === 'all')
        if (am) setAppearancesMin(Number(am) || 0)
        if (sm) setStylesMin(Number(sm) || 0)
        if (
          sb &&
          [
            'consensus_score',
            'appearances',
            'styles_distinct',
            'sources_distinct',
            'rank_best',
            'min_style_rank_pct',
            'symbol',
          ].includes(sb)
        ) {
          setSortBy(sb as SortBy)
        }
        if (sox) setSortOrder(sox)
        if (biasParam && ['all', 'bullish', 'bearish'].includes(biasParam)) setBias(biasParam)
        initializedRef.current = true
        return
      }
    }

    const getAll = (key: string) => (sp.getAll ? sp.getAll(key) : (sp.get(key) ? [sp.get(key)!] : [])) as string[]
    const q = sp.get('q') || sp.get('symbol_filter') || ''
    const st = getAll('styles')
    const so = getAll('sources')
    const sl = sp.get('style_logic') as 'any' | 'all' | null
    const sol = sp.get('source_logic') as 'any' | 'all' | null
    const am = sp.get('appearances_min')
    const sm = sp.get('styles_min')
    const sb = sp.get('sort_by')
    const sox = sp.get('sort_order') as 'asc' | 'desc' | null
    const pg = sp.get('page')
    const biasParam = sp.get('bias') as 'all' | 'bullish' | 'bearish' | null

    if (q) setSearchQuery(q)
    if (st && st.length) setStyles(st)
    else if (normalizedInitialStyles.length) setStyles(normalizedInitialStyles)
    if (so && so.length) setSources(so)
    if (sl) setStyleMatchAll(sl === 'all')
    if (sol) setSourceMatchAll(sol === 'all')
    if (am) setAppearancesMin(Number(am) || 0)
    if (sm) setStylesMin(Number(sm) || 0)
    if (
      sb &&
      [
        'consensus_score',
        'appearances',
        'styles_distinct',
        'sources_distinct',
        'rank_best',
        'min_style_rank_pct',
        'symbol',
      ].includes(sb)
    ) {
      setSortBy(sb as SortBy)
    }
    if (sox) setSortOrder(sox)
    if (pg) setPage(Math.max(1, Number(pg) || 1))
    if (biasParam && ['all', 'bullish', 'bearish'].includes(biasParam)) setBias(biasParam)
    initializedRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (resultsViewParam) {
      setResultsView((prev) => (prev === resultsViewParam ? prev : resultsViewParam))
      hasAppliedResultsView.current = true
      return
    }
    if (hasAppliedResultsView.current) return
    const persisted = readLocalStorageJson<string>(SCREENER_RESULTS_VIEW_KEY)
    if (persisted === 'table' || persisted === 'cards') {
      setResultsView(persisted)
      hasAppliedResultsView.current = true
      return
    }
    setResultsView(isMobile ? 'cards' : 'table')
    hasAppliedResultsView.current = true
  }, [isMobile, resultsViewParam])

  useEffect(() => {
    if (!hasAppliedResultsView.current) return
    writeLocalStorageJson(SCREENER_RESULTS_VIEW_KEY, resultsView)
  }, [resultsView])

  useEffect(() => {
    if (!initializedRef.current) return
    writeLocalStorageJson(SCREENER_FILTERS_STORAGE_KEY, {
      styles,
      sources,
      styleLogic: styleMatchAll ? 'all' : 'any',
      sourceLogic: sourceMatchAll ? 'all' : 'any',
      appearancesMin,
      stylesMin,
      sortBy,
      sortOrder,
      bias,
    } satisfies ScreenerPersistedFilters)
  }, [styles, sources, styleMatchAll, sourceMatchAll, appearancesMin, stylesMin, sortBy, sortOrder, bias])

  type DetailTab = 'changes' | 'breadth' | 'results'
  type PersistedTab = { v: 1; tab: DetailTab }

  const urlTab = useMemo<DetailTab | null>(() => {
    const raw = (searchParams?.get('tab') || '').trim().toLowerCase()
    if (raw === 'changes' || raw === 'breadth' || raw === 'results') return raw as DetailTab
    return null
  }, [searchParams])

  const [tabHydrated, setTabHydrated] = useState(false)
  const [persistedTab, setPersistedTab] = useState<DetailTab | null>(null)

  useEffect(() => {
    const persisted = readLocalStorageJson<PersistedTab>(SCREENER_TAB_STORAGE_KEY)
    if (persisted && persisted.v === 1 && (persisted.tab === 'changes' || persisted.tab === 'breadth' || persisted.tab === 'results')) {
      setPersistedTab(persisted.tab)
    }
    setTabHydrated(true)
  }, [])

  const activeTab = (urlTab ?? persistedTab ?? 'results') satisfies DetailTab
  const tabDescriptor =
    activeTab === 'results'
      ? 'Find candidates that match these screens.'
      : activeTab === 'changes'
        ? 'What entered or exited screens recently.'
        : 'How many names are rotating into or out of styles.'

  useEffect(() => {
    if (!tabHydrated) return
    if (urlTab) {
      writeLocalStorageJson(SCREENER_TAB_STORAGE_KEY, { v: 1, tab: urlTab })
      return
    }
    if (!persistedTab) {
      writeLocalStorageJson(SCREENER_TAB_STORAGE_KEY, { v: 1, tab: 'results' })
    }
  }, [tabHydrated, urlTab, persistedTab])

  useEffect(() => {
    if (!tabHydrated) return
    if (urlTab) return
    if (!persistedTab || persistedTab === 'results') return

    const basePath = pathname || window.location.pathname
    if (!basePath.startsWith('/screener')) return

    const params = new URLSearchParams(searchParams.toString())
    params.set('tab', persistedTab)
    params.delete('views')
    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    const currentUrl = `${window.location.pathname}${window.location.search}`
    if (nextUrl === currentUrl) return
    router.replace(nextUrl, { scroll: false })
  }, [pathname, router, searchParams, tabHydrated, urlTab, persistedTab])

  const consensusParams = useMemo<Parameters<typeof api.listScreenerConsensus>[0]>(
    () => ({
      symbol: symbolFilter || undefined,
      styles: symbolFilter ? undefined : styles.length ? styles : undefined,
      sources: symbolFilter ? undefined : sources.length ? sources : undefined,
      style_logic: symbolFilter ? 'all' : styleMatchAll ? 'all' : 'any',
      source_logic: symbolFilter ? 'all' : sourceMatchAll ? 'all' : 'any',
      appearances_min: symbolFilter ? undefined : appearancesMin || undefined,
      styles_min: symbolFilter ? undefined : stylesMin || undefined,
      skip: symbolFilter ? 0 : (page - 1) * pageSize,
      limit: symbolFilter ? 1 : pageSize,
      sort_by: sortBy,
      sort_order: sortOrder,
      position_side: symbolFilter ? undefined : positionSide,
    }),
    [
      symbolFilter,
      styles,
      sources,
      styleMatchAll,
      sourceMatchAll,
      appearancesMin,
      stylesMin,
      page,
      pageSize,
      sortBy,
      sortOrder,
      positionSide,
    ]
  )

  const consensusQueryKey = useMemo(
    () => ['screener-consensus', symbolFilter, stylesKey, sourcesKey, styleMatchAll, sourceMatchAll, appearancesMin, stylesMin, page, sortBy, sortOrder, bias],
    [symbolFilter, stylesKey, sourcesKey, styleMatchAll, sourceMatchAll, appearancesMin, stylesMin, page, sortBy, sortOrder, bias]
  )

  const { data, isLoading, isError, error: screenerErrorRaw, refetch: refetchScreener } = useQuery({
    queryKey: consensusQueryKey,
    queryFn: () => api.listScreenerConsensus(consensusParams),
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    enabled: activeTab === 'results' || activeTab === 'changes',
  })

  type MovementFilter = 'entered' | 'reentered' | 'dropped' | 'entrants'
  const movementParamRaw = (searchParams?.get('movement') || '').trim().toLowerCase()
  const movementParam: MovementFilter | null =
    movementParamRaw === 'entered' || movementParamRaw === 'reentered' || movementParamRaw === 'dropped' || movementParamRaw === 'entrants'
      ? (movementParamRaw as MovementFilter)
      : null
  const movementStyleParam = (searchParams?.get('movement_style') || '').trim()
  const movementWindowParam = useMemo(() => {
    const raw = (searchParams?.get('movement_window') || '').trim()
    const parsed = Number(raw)
    if (!raw) return null
    if (!Number.isFinite(parsed)) return null
    return Math.max(1, Math.min(30, Math.round(parsed)))
  }, [searchParams])

  const [movementFilter, setMovementFilter] = useState<MovementFilter | null>(movementParam)
  const [movementStyle, setMovementStyle] = useState<string | null>(movementStyleParam || null)
  const [movementWindowDays, setMovementWindowDays] = useState<number>(movementWindowParam ?? DEFAULT_MOVEMENT_WINDOW_DAYS)

  const movementRange = useMemo(() => {
    const end = formatEasternDate(new Date())
    const offset = Math.max(0, movementWindowDays - 1)
    const start = offset ? dateDaysAgo(offset) : end
    return { start, end }
  }, [movementWindowDays])

  const changesParams = useMemo<Parameters<typeof api.listScreenerChanges>[0]>(
    () => ({
      symbol: symbolFilter || undefined,
      styles: symbolFilter ? undefined : styles.length ? styles : undefined,
      sources: symbolFilter ? undefined : sources.length ? sources : undefined,
      change_types: ['entered', 'reentered', 'dropped'] as ScreenerChangeType[],
      start_date: movementRange.start,
      end_date: movementRange.end,
      limit: 200,
      sort_by: 'change_date',
      sort_order: 'desc',
      position_side: symbolFilter ? undefined : positionSide,
    }),
    [symbolFilter, styles, sources, positionSide, movementRange]
  )

  const changesQueryKey = useMemo(
    () => ['screener-changes', symbolFilter, stylesKey, sourcesKey, styleMatchAll, sourceMatchAll, bias, movementWindowDays],
    [symbolFilter, stylesKey, sourcesKey, styleMatchAll, sourceMatchAll, bias, movementWindowDays]
  )

  const { data: changeData, isLoading: changesLoading, isError: changesError, error: changesErrorRaw, refetch: refetchChanges } = useQuery({
    queryKey: changesQueryKey,
    queryFn: () => api.listScreenerChanges(changesParams),
    staleTime: TWO_MIN_MS,
    enabled: activeTab === 'changes',
  })

  useEffect(() => {
    setMovementFilter(movementParam)
  }, [movementParam])

  useEffect(() => {
    setMovementStyle(movementStyleParam || null)
  }, [movementStyleParam])

  useEffect(() => {
    if (movementWindowParam === null) {
      setMovementWindowDays(DEFAULT_MOVEMENT_WINDOW_DAYS)
      return
    }
    setMovementWindowDays(movementWindowParam)
  }, [movementWindowParam])

  const openMovementResults = (next: MovementFilter, opts?: { style?: string | null }) => {
    const nextStyle = opts?.style ?? null
    setMovementFilter(next)
    setMovementStyle(nextStyle)
    setPage(1)

    const basePath = pathname || window.location.pathname
    if (!basePath.startsWith('/screener')) return
    const params = new URLSearchParams(searchParams.toString())
    params.set('tab', 'results')
    params.set('movement', next)
    if (nextStyle) params.set('movement_style', nextStyle)
    else params.delete('movement_style')
    params.delete('views')
    params.delete('page')
    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl, { scroll: false })
  }

  const expandMovementWindow = (days: number) => {
    const next = Math.max(1, Math.min(30, Math.round(days)))
    setMovementWindowDays(next)
    setPage(1)
  }

  const relaxMovementFilters = () => {
    setStyles([])
    setSources([])
    setStyleMatchAll(true)
    setSourceMatchAll(true)
    setAppearancesMin(0)
    setStylesMin(0)
    setPage(1)
  }

  const clearMovementResults = () => {
    setMovementFilter(null)
    setMovementStyle(null)
    setPage(1)

    const basePath = pathname || window.location.pathname
    if (!basePath.startsWith('/screener')) return
    const params = new URLSearchParams(searchParams.toString())
    params.delete('movement')
    params.delete('movement_style')
    params.delete('page')
    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl, { scroll: false })
  }

  // toggle breadth mode via URL (?breadth=flow|legacy), default flow
  const breadthModeParam = (searchParams?.get('breadth') as 'flow' | 'legacy' | null) || 'flow'
  const breadthModeExplicit = Boolean(searchParams?.get('breadth'))
  const [breadthMode, setBreadthMode] = useState<'flow' | 'legacy'>(breadthModeParam)

  useEffect(() => {
    setBreadthMode(breadthModeParam)
  }, [breadthModeParam])

  const resultsColumnsKey = useMemo(() => resultsColumns.join(','), [resultsColumns])
  const resultsScrollKey = useMemo(() => {
    return [
      activeTab,
      searchQuery,
      symbolFilter,
      stylesKey,
      sourcesKey,
      styleMatchAll ? 'all' : 'any',
      sourceMatchAll ? 'all' : 'any',
      appearancesMin,
      stylesMin,
      sortBy,
      sortOrder,
      bias,
      movementFilter ?? '',
      movementStyle ?? '',
      movementWindowDays,
      breadthMode,
      resultsView,
      resultsColumnsKey,
    ].join('|')
  }, [
    activeTab,
    searchQuery,
    symbolFilter,
    stylesKey,
    sourcesKey,
    styleMatchAll,
    sourceMatchAll,
    appearancesMin,
    stylesMin,
    sortBy,
    sortOrder,
    bias,
    movementFilter,
    movementStyle,
    movementWindowDays,
    breadthMode,
    resultsView,
    resultsColumnsKey,
  ])

  const breadthFlowParams = useMemo<Parameters<typeof api.listScreenerBreadthFlow>[0]>(
    () => ({ styles: styles.length ? styles : undefined, limit: 180, sort_order: 'desc' as const }),
    [styles]
  )
  const breadthFlowQueryKey = useMemo(() => ['screener-breadth-flow', stylesKey, bias], [stylesKey, bias])
  const {
    data: breadthFlowData,
    isLoading: breadthFlowLoading,
    isError: breadthFlowError,
    refetch: refetchBreadthFlow,
  } = useQuery({
    queryKey: breadthFlowQueryKey,
    queryFn: () => api.listScreenerBreadthFlow(breadthFlowParams),
    staleTime: FIVE_MIN_MS,
    enabled: activeTab === 'breadth',
  })

  const breadthLegacyParams = useMemo<Parameters<typeof api.listScreenerBreadth>[0]>(
    () => ({
      styles: styles.length ? styles : undefined,
      limit: 180,
      sort_order: 'desc' as const,
      position_side: positionSide,
    }),
    [styles, positionSide]
  )
  const breadthLegacyQueryKey = useMemo(() => ['screener-breadth-legacy', stylesKey, bias], [stylesKey, bias])
  const {
    data: breadthLegacyData,
    isLoading: breadthLegacyLoading,
    isError: breadthLegacyError,
    refetch: refetchBreadthLegacy,
  } = useQuery({
    queryKey: breadthLegacyQueryKey,
    queryFn: () => api.listScreenerBreadth(breadthLegacyParams),
    staleTime: FIVE_MIN_MS,
    enabled: activeTab === 'breadth',
  })

  const prefetchTab = useCallback(
    (tab: DetailTab) => {
      if (tab === activeTab) return

      if (tab === 'results') {
        queryClient.prefetchQuery({
          queryKey: consensusQueryKey,
          queryFn: () => api.listScreenerConsensus(consensusParams),
        })
        return
      }

      if (tab === 'changes') {
        queryClient.prefetchQuery({
          queryKey: changesQueryKey,
          queryFn: () => api.listScreenerChanges(changesParams),
          staleTime: TWO_MIN_MS,
        })
        return
      }

      if (tab === 'breadth') {
        queryClient.prefetchQuery({
          queryKey: breadthFlowQueryKey,
          queryFn: () => api.listScreenerBreadthFlow(breadthFlowParams),
          staleTime: FIVE_MIN_MS,
        })
        queryClient.prefetchQuery({
          queryKey: breadthLegacyQueryKey,
          queryFn: () => api.listScreenerBreadth(breadthLegacyParams),
          staleTime: FIVE_MIN_MS,
        })
      }
    },
    [
      activeTab,
      queryClient,
      consensusQueryKey,
      consensusParams,
      changesQueryKey,
      changesParams,
      breadthFlowQueryKey,
      breadthFlowParams,
      breadthLegacyQueryKey,
      breadthLegacyParams,
    ]
  )
  const useFlowBreadth = breadthMode === 'flow'
  const flowItems = useMemo(() => breadthFlowData?.items ?? [], [breadthFlowData?.items])
  const legacyItems = useMemo(() => breadthLegacyData?.items ?? [], [breadthLegacyData?.items])

  // Reset to page 1 on filter/sort changes (skip initial URL restore)
  useEffect(() => {
    if (!initializedRef.current) return
    if (suspendUrlSyncRef.current) return
    setPage(1)
  }, [appearancesMin, stylesMin, sortBy, sortOrder, stylesKey, sourcesKey, styleMatchAll, sourceMatchAll, bias, symbolFilter])

  useEffect(() => {
    if (!initializedRef.current) return
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

  // Sync state -> URL (replace)
  useEffect(() => {
    if (!initializedRef.current) return
    if (suspendUrlSyncRef.current) return
    const params = new URLSearchParams()
    if (urlSearchQuery) params.set('q', urlSearchQuery)
    styles.forEach(s => params.append('styles', s))
    sources.forEach(s => params.append('sources', s))
    params.set('style_logic', styleMatchAll ? 'all' : 'any')
    params.set('source_logic', sourceMatchAll ? 'all' : 'any')
    if (appearancesMin) params.set('appearances_min', String(appearancesMin))
    if (stylesMin) params.set('styles_min', String(stylesMin))
    params.set('sort_by', sortBy)
    params.set('sort_order', sortOrder)
    params.set('page', String(page))
    if (bias && bias !== 'all') params.set('bias', bias)
    if (movementFilter) params.set('movement', movementFilter)
    if (movementStyle) params.set('movement_style', movementStyle)
    if (movementWindowDays !== DEFAULT_MOVEMENT_WINDOW_DAYS) params.set('movement_window', String(movementWindowDays))
    if (breadthMode !== 'flow') params.set('breadth', breadthMode)
    params.set(RESULTS_VIEW_PARAM_KEY, resultsView)
    params.set(RESULTS_COLUMNS_PARAM_KEY, resultsColumns.join(','))
    const persistedSource = new URLSearchParams(searchParamsString)
    const viewsRaw = (persistedSource.get('views') || '').trim().toLowerCase()
    if (viewsRaw === '1' || viewsRaw === 'true' || viewsRaw === 'yes') params.set('views', '1')
    const tabRaw = (persistedSource.get('tab') || '').trim().toLowerCase()
    if (tabRaw === 'changes' || tabRaw === 'breadth' || tabRaw === 'results') params.set('tab', tabRaw)
    persistKeys.forEach((key) => {
      const values = persistedSource.getAll(key)
      if (!values.length) return
      params.delete(key)
      values.forEach((value) => params.append(key, value))
    })
    const qs = params.toString()
    if (qs === searchParamsString) return
    const basePath = pathname || window.location.pathname
    if (!basePath.startsWith('/screener')) return
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl)
  }, [router, pathname, urlSearchQuery, styles, sources, styleMatchAll, sourceMatchAll, appearancesMin, stylesMin, sortBy, sortOrder, page, bias, movementFilter, movementStyle, movementWindowDays, breadthMode, resultsView, resultsColumns, searchParamsString, persistKeySignature, persistKeys])

  const items = useMemo(() => data?.items ?? [], [data?.items])
  const latestAsOf = useMemo(() => {
    if (!items.length) return null
    return items.reduce((acc, it) => (acc > it.as_of_date ? acc : it.as_of_date), items[0].as_of_date)
  }, [items])
  const lastUpdatedLabel = useMemo(() => {
    return latestAsOf ? formatEasternDate(latestAsOf) : null
  }, [latestAsOf])
  const filteredItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return items
    if (symbolFilter) return items
    return items.filter((row) => {
      const sym = (row.symbol || '').toLowerCase()
      const name = (row.company_name || '').toLowerCase()
      return sym.includes(q) || name.includes(q)
    })
  }, [items, searchQuery, symbolFilter])

  const sparklineSymbols = useMemo(() => {
    if (!showSparklines || isMobile || resultsView !== 'table') return []
    return filteredItems.map((row) => (row.symbol || '').trim().toUpperCase()).filter(Boolean)
  }, [filteredItems, isMobile, resultsView, showSparklines])

  const { data: sparklineMap } = useQuery({
    queryKey: ['screener-sparklines', sparklineSymbols.join(',')],
    queryFn: () => fetchSparklinePriceMap(sparklineSymbols, 40),
    enabled: sparklineSymbols.length > 0,
    staleTime: 120_000,
  })
  const sparklineBySymbol = sparklineMap ?? {}
  const total = data?.total_count || 0
  const statusLabel = isError ? 'Status: delayed' : isLoading ? 'Status: loading' : 'Status: live'
  const headerContextBadges = [
    latestAsOf ? `As of ${formatEasternDate(latestAsOf)}` : null,
    total ? `Universe ${total.toLocaleString()}` : null,
    statusLabel,
  ].filter(Boolean)
  const resultsLoading = isLoading || (activeTab !== 'results' && !data)
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const filterKey = useMemo(() => {
    const params = new URLSearchParams(searchParamsString)
    params.delete('page')
    return params.toString()
  }, [searchParamsString])
  const { delta: countDelta } = useCountDeltaBadge(total, filterKey)
  const activeFilterChips = useMemo(() => {
    const chips: Array<{ key: string; label: string; onRemove?: () => void }> = []

    const q = searchQuery.trim()
    if (q) chips.push({ key: 'q', label: `Search: ${q}`, onRemove: () => setSearchQuery('') })

    if (bias !== 'all') chips.push({ key: 'bias', label: `Bias: ${bias}`, onRemove: () => setBias('all') })

    if (styles.length) {
      const logic = styleMatchAll ? null : 'any'
      chips.push({
        key: 'styles',
        label: `Styles (${styles.length}${logic ? `, ${logic}` : ''})`,
        onRemove: () => {
          setStyles([])
          setStyleMatchAll(true)
        },
      })
    } else if (!styleMatchAll) {
      chips.push({ key: 'style_logic', label: 'Styles: any', onRemove: () => setStyleMatchAll(true) })
    }

    if (sources.length) {
      const logic = sourceMatchAll ? null : 'any'
      chips.push({
        key: 'sources',
        label: `Screens (${sources.length}${logic ? `, ${logic}` : ''})`,
        onRemove: () => {
          setSources([])
          setSourceMatchAll(true)
        },
      })
    } else if (!sourceMatchAll) {
      chips.push({ key: 'source_logic', label: 'Screens: any', onRemove: () => setSourceMatchAll(true) })
    }

    if (appearancesMin > 0) {
      chips.push({
        key: 'appearances_min',
        label: `Min appearances: ${appearancesMin}`,
        onRemove: () => setAppearancesMin(0),
      })
    }
    if (stylesMin > 0) {
      chips.push({
        key: 'styles_min',
        label: `Min styles: ${stylesMin}`,
        onRemove: () => setStylesMin(0),
      })
    }

    if (movementFilter) {
      const label =
        movementFilter === 'entrants'
          ? 'Entrants'
          : movementFilter === 'entered'
            ? 'New entrants'
            : movementFilter === 'reentered'
              ? 'Re-entries'
              : 'Drops'
      chips.push({
        key: 'movement',
        label: `Movement: ${label}`,
        onRemove: () => {
          setMovementFilter(null)
          setMovementStyle(null)
        },
      })
    }
    if (movementFilter && movementStyle) {
      chips.push({
        key: 'movement_style',
        label: `Movement style: ${movementStyle}`,
        onRemove: () => setMovementStyle(null),
      })
    }
    if (movementWindowDays !== DEFAULT_MOVEMENT_WINDOW_DAYS) {
      chips.push({
        key: 'movement_window',
        label: `Movement window: ${movementWindowDays}d`,
        onRemove: () => setMovementWindowDays(DEFAULT_MOVEMENT_WINDOW_DAYS),
      })
    }

    if (breadthMode !== 'flow') {
      chips.push({ key: 'breadth', label: `Breadth: ${breadthMode}`, onRemove: () => setBreadthMode('flow') })
    }

    chips.push({
      key: 'sort',
      label: `Sort: ${sortBy.replace(/_/g, ' ')} (${sortOrder.toUpperCase()})`,
      onRemove: () => {
        setSortBy('consensus_score')
        setSortOrder('desc')
      },
    })

    return chips
  }, [appearancesMin, bias, breadthMode, movementFilter, movementStyle, movementWindowDays, searchQuery, setAppearancesMin, setBias, setBreadthMode, setMovementFilter, setMovementStyle, setMovementWindowDays, setSearchQuery, setSources, setSourceMatchAll, setStyleMatchAll, setStyles, setStylesMin, sortBy, sortOrder, sourceMatchAll, sources.length, styleMatchAll, styles.length, stylesMin])

  const { currentSavedViewQuery, savedViewsBasePath, buildSavedViewUrlForQuery } = useSavedViewsLinks({
    pathname,
    fallbackPath: '/screener',
    searchParams,
  })

  const shareCurrentView = useShareCurrentView({
    failureDescription: 'Your browser blocked clipboard access.',
  })

  const changeItemsSource = changeData?.items
  const changeItems = useMemo<ScreenerChangeItem[]>(() => changeItemsSource ?? [], [changeItemsSource])
  const latestChangeDate = changeItems.length ? changeItems[0].change_date : undefined
  const enteredChanges = useMemo(() => {
    const arr = changeItems.filter(it => it.change_type === 'entered')
    const matchesBias = (it: ScreenerChangeItem) => {
      if (bias === 'all') return true
      const isBearish = it.regime_bias ? it.regime_bias === 'Bearish' : (it.position_side === 'short')
      return bias === 'bullish' ? !isBearish : isBearish
    }
    const biasRank = (it: ScreenerChangeItem) => {
      const bias = it.regime_bias
      if (bias === 'Bearish') return 0
      if (bias === 'Bullish') return 1
      return it.position_side === 'short' ? 0 : 1
    }
    return [...arr].filter(matchesBias).sort((a, b) => {
      const r = biasRank(a) - biasRank(b)
      if (r !== 0) return r
      return (a.symbol || '').localeCompare(b.symbol || '')
    })
  }, [changeItems, bias])
  const reenteredChanges = useMemo(() => {
    const arr = changeItems.filter(it => it.change_type === 'reentered')
    const matchesBias = (it: ScreenerChangeItem) => {
      if (bias === 'all') return true
      const isBearish = it.regime_bias ? it.regime_bias === 'Bearish' : (it.position_side === 'short')
      return bias === 'bullish' ? !isBearish : isBearish
    }
    const biasRank = (it: ScreenerChangeItem) => {
      const bias = it.regime_bias
      if (bias === 'Bearish') return 0
      if (bias === 'Bullish') return 1
      return it.position_side === 'short' ? 0 : 1
    }
    return [...arr].filter(matchesBias).sort((a, b) => {
      const r = biasRank(a) - biasRank(b)
      if (r !== 0) return r
      return (a.symbol || '').localeCompare(b.symbol || '')
    })
  }, [changeItems, bias])
  const droppedChanges = useMemo(() => {
    const arr = changeItems.filter(it => it.change_type === 'dropped')
    const matchesBias = (it: ScreenerChangeItem) => {
      if (bias === 'all') return true
      const isBearish = it.regime_bias ? it.regime_bias === 'Bearish' : (it.position_side === 'short')
      return bias === 'bullish' ? !isBearish : isBearish
    }
    const biasRank = (it: ScreenerChangeItem) => {
      const bias = it.regime_bias
      if (bias === 'Bearish') return 0
      if (bias === 'Bullish') return 1
      return it.position_side === 'short' ? 0 : 1
    }
    return [...arr].filter(matchesBias).sort((a, b) => {
      const r = biasRank(a) - biasRank(b)
      if (r !== 0) return r
      return (a.symbol || '').localeCompare(b.symbol || '')
    })
  }, [changeItems, bias])

  const enteredCount = enteredChanges.length
  const reenteredCount = reenteredChanges.length
  const droppedCount = droppedChanges.length
  const movementsNet = enteredCount + reenteredCount - droppedCount
  const enteredDisabled = changesLoading || changesError || enteredCount === 0
  const reenteredDisabled = changesLoading || changesError || reenteredCount === 0
  const droppedDisabled = changesLoading || changesError || droppedCount === 0
  const [triageOpen, setTriageOpen] = useState(false)
  const [triageFocus, setTriageFocus] = useState<TriageFocus>('entered')

  const openTriage = (focus: TriageFocus) => {
    setTriageFocus(focus)
    setTriageOpen(true)
  }

  const triageEntered = useMemo(() => sortMovementTriage(enteredChanges, 'up'), [enteredChanges])
  const triageReentered = useMemo(() => sortMovementTriage(reenteredChanges, 'up'), [reenteredChanges])
  const triageDropped = useMemo(() => sortMovementTriage(droppedChanges, 'down'), [droppedChanges])

  const triageItems = triageFocus === 'entered' ? triageEntered : triageFocus === 'reentered' ? triageReentered : triageDropped
  const triageTitle = triageFocus === 'entered' ? 'New Entrants' : triageFocus === 'reentered' ? 'Re-entries' : 'Confirmed Drops'

  const movementListTitle =
    movementFilter === 'entrants'
      ? 'Entrants'
      : movementFilter === 'entered'
        ? 'New Entrants'
        : movementFilter === 'reentered'
          ? 'Re-entries'
          : movementFilter === 'dropped'
            ? 'Drops'
            : null
  const movementEmptyMessageBase =
    movementFilter === 'entered'
      ? `No first-time entrants in the last ${movementWindowDays} days.`
      : movementFilter === 'reentered'
        ? `No re-entries in the last ${movementWindowDays} days.`
        : movementFilter === 'dropped'
          ? `No drops in the last ${movementWindowDays} days.`
          : `No entrants in the last ${movementWindowDays} days.`
  const showExpandWindowAction = movementWindowDays < 10
  const movementEmptyMessage = showExpandWindowAction
    ? `${movementEmptyMessageBase} Try increasing the window.`
    : movementEmptyMessageBase
  const movementWindowLabel = movementWindowDays === 1 ? '1 trading day' : `${movementWindowDays} trading days`
  const movementCardEmptyText = (kind: 'entered' | 'reentered' | 'dropped') => {
    if (kind === 'entered') return `No new entrants in the last ${movementWindowLabel}.`
    if (kind === 'reentered') return `No re-entries in the last ${movementWindowLabel}.`
    return `No drops in the last ${movementWindowLabel}.`
  }
  const movementColumnEmptyLabels = {
    entered: `No first-time appearances in the last ${movementWindowLabel}.`,
    reentered: `No re-entries after cooling off in the last ${movementWindowLabel}.`,
    dropped: `No drops confirmed in the last ${movementWindowLabel}.`,
  }
  const movementListItems = useMemo(() => {
    if (!movementFilter) return []
    const base =
      movementFilter === 'entrants'
        ? [...triageEntered, ...triageReentered].sort((a, b) => (a.symbol || '').localeCompare(b.symbol || ''))
        : movementFilter === 'entered'
          ? triageEntered
          : movementFilter === 'reentered'
            ? triageReentered
            : triageDropped

    const desiredStyle = (movementStyle || '').trim().toLowerCase()
    const q = searchQuery.trim().toLowerCase()

    return base.filter((it) => {
      if (desiredStyle) {
        const style = (it.style || '').trim().toLowerCase()
        if (style !== desiredStyle) return false
      }
      if (!q) return true
      const sym = (it.symbol || '').trim().toLowerCase()
      const name = (it.company_name || '').trim().toLowerCase()
      return sym.includes(q) || name.includes(q)
    })
  }, [movementFilter, movementStyle, searchQuery, triageDropped, triageEntered, triageReentered])
  const changeHighlights = useMemo(() => {
    return changeItems.reduce<Map<string, ScreenerChangeItem[]>>((acc, item) => {
      if (!acc.has(item.symbol)) acc.set(item.symbol, [])
      acc.get(item.symbol)!.push(item)
      return acc
    }, new Map())
  }, [changeItems])

  const [breadthDrilldown, setBreadthDrilldown] = useState<{
    style: string
    bias: 'Bullish' | 'Bearish' | null
  } | null>(null)

  const clearFilters = useCallback(() => {
    removeLocalStorageItem(SCREENER_FILTERS_STORAGE_KEY)
    setSearchQuery('')
    setStyles([])
    setSources([])
    setStyleMatchAll(true)
    setSourceMatchAll(true)
    setAppearancesMin(0)
    setStylesMin(0)
    setBias('all')
    setSortBy('consensus_score')
    setSortOrder('desc')
    setMovementFilter(null)
    setMovementStyle(null)
    setMovementWindowDays(DEFAULT_MOVEMENT_WINDOW_DAYS)
    setBreadthMode('flow')
    setBreadthDrilldown(null)
    setPage(1)
  }, [
    setAppearancesMin,
    setBias,
    setBreadthMode,
    setBreadthDrilldown,
    setMovementFilter,
    setMovementStyle,
    setMovementWindowDays,
    setPage,
    setSearchQuery,
    setSortBy,
    setSortOrder,
    setSourceMatchAll,
    setSources,
    setStyleMatchAll,
    setStyles,
    setStylesMin,
  ])

  const { applySavedView, buildSavedViewUrlForView } = useScreenerSavedView({
    savedViewsBasePath,
    normalizedInitialStyles,
    defaultMovementWindowDays: DEFAULT_MOVEMENT_WINDOW_DAYS,
    router,
    toast,
    suspendUrlSyncRef,
    tabStorageKey: SCREENER_TAB_STORAGE_KEY,
    setSearchQuery,
    setStyles,
    setSources,
    setStyleMatchAll,
    setSourceMatchAll,
    setAppearancesMin,
    setStylesMin,
    setSortBy,
    setSortOrder,
    setBias,
    setMovementFilter,
    setMovementStyle,
    setMovementWindowDays,
    setBreadthMode,
    setBreadthDrilldown,
    setPage,
  })

  const breadthDrillItems = useMemo(() => {
    if (!breadthDrilldown) return null
    const desiredStyle = breadthDrilldown.style.trim().toLowerCase()
    const desiredBias = breadthDrilldown.bias

    const styleItems = changeItems
      .filter((it) => (it.style || '').trim().toLowerCase() === desiredStyle)
      .filter((it) => {
        if (!desiredBias) return true
        if (!it.regime_bias) return true
        return it.regime_bias === desiredBias
      })

    const entrants = styleItems
      .filter((it) => it.change_type === 'entered' || it.change_type === 'reentered')
      .sort((a, b) => (a.symbol || '').localeCompare(b.symbol || ''))
    const drops = styleItems
      .filter((it) => it.change_type === 'dropped')
      .sort((a, b) => (a.symbol || '').localeCompare(b.symbol || ''))

    return { entrants, drops }
  }, [breadthDrilldown, changeItems])

  const useFlow = useFlowBreadth
  const hasFlowRows = flowItems.length > 0
  const hasLegacyRows = legacyItems.length > 0
  useEffect(() => {
    if (!breadthModeExplicit && breadthMode === 'flow' && !breadthFlowLoading && !hasFlowRows && hasLegacyRows) {
      setBreadthMode('legacy')
    }
  }, [breadthModeExplicit, breadthMode, breadthFlowLoading, hasFlowRows, hasLegacyRows])
  const breadthItemsFlowFiltered = useMemo<ScreenerBreadthFlowItem[]>(() => {
    if (!useFlow) return []
    if (bias === 'all') return flowItems
    const desired = bias === 'bullish' ? 'Bullish' : 'Bearish'
    return flowItems.filter(item => item.regime_bias === desired)
  }, [flowItems, useFlow, bias])
  const latestBreadthDate = useFlow
    ? (breadthItemsFlowFiltered.length ? breadthItemsFlowFiltered[0].change_date : undefined)
    : (legacyItems.length ? legacyItems[0].change_date : undefined)
  const latestBreadthRowsFlow = useMemo<ScreenerBreadthFlowItem[]>(() => {
    if (!useFlow) return []
    if (!breadthItemsFlowFiltered.length) return []

    const latestDate = breadthItemsFlowFiltered[0].change_date
    const biasRank = (label?: string) => (label === 'Bullish' ? 0 : 1)
    return breadthItemsFlowFiltered
      .filter((item) => item.change_date === latestDate)
      .sort((a, b) => {
        const rankDiff = biasRank(a.regime_bias) - biasRank(b.regime_bias)
        if (rankDiff !== 0) return rankDiff
        return a.canonical_name.localeCompare(b.canonical_name)
      })
  }, [breadthItemsFlowFiltered, useFlow])

  const latestBreadthRowsLegacy = useMemo<ScreenerBreadthItem[]>(() => {
    if (useFlow) return []
    if (!legacyItems.length) return []

    const latestDate = legacyItems[0].change_date
    const biasRank = (label?: string) => (label === 'Bullish' ? 0 : 1)
    return legacyItems
      .filter((item) => item.change_date === latestDate)
      .sort((a, b) => {
        const rankDiff = biasRank(a.regime_bias) - biasRank(b.regime_bias)
        if (rankDiff !== 0) return rankDiff
        return a.style_name.localeCompare(b.style_name)
      })
  }, [legacyItems, useFlow])

  const latestBreadthRows = useFlow ? latestBreadthRowsFlow : latestBreadthRowsLegacy
  const breadthSummary = useMemo(() => {
    const rows = useFlow ? latestBreadthRowsFlow : latestBreadthRowsLegacy
    if (!rows.length) return null

    if (useFlow) {
      const universe = latestBreadthRowsFlow[0]?.eligible_count ?? 0
      const latestWeights = latestBreadthRowsFlow.reduce((sum, row) => sum + row.eligible_count, 0)
      const netPctWeighted = latestWeights
        ? latestBreadthRowsFlow.reduce(
            (sum, row) => sum + row.net_pct_us_signed * row.eligible_count,
            0,
          ) / latestWeights
        : 0

      // Use the last 5 trading days (or fewer if unavailable) for the flow baseline
      const uniqueDates = Array.from(new Set(breadthItemsFlowFiltered.map(row => row.change_date)))
      const windowDates = uniqueDates.slice(0, 5)
      const windowRows = breadthItemsFlowFiltered.filter((row) => windowDates.includes(row.change_date))
      const windowWeights = windowRows.reduce((sum, row) => sum + row.eligible_count, 0)
      const netPctAvg5dWeighted = windowWeights
        ? windowRows.reduce(
            (sum, row) => sum + row.net_pct_us_signed * row.eligible_count,
            0,
          ) / windowWeights
        : netPctWeighted

      const enteredShare = latestWeights
        ? latestBreadthRowsFlow.reduce(
            (sum, row) => sum + row.entered_pct * row.eligible_count,
            0,
          ) / latestWeights
        : 0
      const droppedShare = latestWeights
        ? latestBreadthRowsFlow.reduce(
            (sum, row) => sum + row.dropped_pct * row.eligible_count,
            0,
          ) / latestWeights
        : 0

      return {
        totalEligible: universe,
        totalEntered: Math.round(universe * enteredShare),
        totalDropped: Math.round(universe * droppedShare),
        enteredShare,
        droppedShare,
        netPctWeighted,
        netPctAvg5dWeighted,
      }
    }

    const totalEligible = latestBreadthRowsLegacy.reduce((sum, row) => sum + row.eligible_count, 0)
    const totalEntered = latestBreadthRowsLegacy.reduce((sum, row) => sum + row.entered_count, 0)
    const totalDropped = latestBreadthRowsLegacy.reduce((sum, row) => sum + row.dropped_count, 0)
    const netPctWeighted = totalEligible
      ? latestBreadthRowsLegacy.reduce((sum, row) => sum + row.net_pct_signed * row.eligible_count, 0) / totalEligible
      : 0
    const netPctAvg5dWeighted = totalEligible
      ? latestBreadthRowsLegacy.reduce(
          (sum, row) => sum + row.net_pct_avg_5d_signed * row.eligible_count,
          0,
        ) / totalEligible
      : 0
    const enteredShare = totalEligible ? totalEntered / totalEligible : 0
    const droppedShare = totalEligible ? totalDropped / totalEligible : 0
    return { totalEligible, totalEntered, totalDropped, enteredShare, droppedShare, netPctWeighted, netPctAvg5dWeighted }
  }, [breadthItemsFlowFiltered, latestBreadthRowsFlow, latestBreadthRowsLegacy, useFlow])

  const activeBreadthLoading = useFlow ? breadthFlowLoading : breadthLegacyLoading
  const activeBreadthError = useFlow ? breadthFlowError : breadthLegacyError
  const activeBreadthRefetch = useFlow ? refetchBreadthFlow : refetchBreadthLegacy
  const [breadthSort, setBreadthSort] = useState<{ key: 'entered' | 'dropped' | 'net'; dir: 'asc' | 'desc' }>({
    key: 'net',
    dir: 'desc',
  })
  const [breadthPins, setBreadthPins] = useState<string[]>([])

  useEffect(() => {
    const saved = readLocalStorageJson<string[]>(SCREENER_BREADTH_PIN_KEY)
    if (Array.isArray(saved)) setBreadthPins(saved)
  }, [])

  useEffect(() => {
    writeLocalStorageJson(SCREENER_BREADTH_PIN_KEY, breadthPins)
  }, [breadthPins])

  const pinnedSet = useMemo(() => new Set(breadthPins), [breadthPins])

  const toggleBreadthPin = (key: string) => {
    setBreadthPins((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
  }

  const handleBreadthSort = (key: 'entered' | 'dropped' | 'net') => {
    setBreadthSort((prev) => {
      if (prev.key === key) {
        return { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
      }
      return { key, dir: 'desc' }
    })
  }

  const sortedBreadthRows = useMemo(() => {
    if (!latestBreadthRows.length) return []
    const rows = [...latestBreadthRows]
    const getBreadthName = (row: ScreenerBreadthFlowItem | ScreenerBreadthItem) =>
      ('canonical_name' in row ? row.canonical_name : row.style_name) || ''
    const getKey = (row: ScreenerBreadthFlowItem | ScreenerBreadthItem) => {
      const styleName = getBreadthName(row)
      const biasLabel = row.regime_bias || 'Neutral'
      return `${biasLabel}:${styleName}`
    }
    const valueFor = (row: ScreenerBreadthFlowItem | ScreenerBreadthItem) => {
      if (breadthSort.key === 'entered') return Number(row.entered_count || 0)
      if (breadthSort.key === 'dropped') return Number(row.dropped_count || 0)
      return Number('net_pct_us_signed' in row ? (row.net_pct_us_signed ?? 0) : (row.net_pct_signed ?? 0))
    }
    const dir = breadthSort.dir === 'asc' ? 1 : -1
    rows.sort((a, b) => {
      const pinA = pinnedSet.has(getKey(a)) ? 1 : 0
      const pinB = pinnedSet.has(getKey(b)) ? 1 : 0
      if (pinA !== pinB) return pinB - pinA
      const diff = valueFor(a) - valueFor(b)
      if (diff !== 0) return diff * dir
      const nameA = getBreadthName(a)
      const nameB = getBreadthName(b)
      return nameA.localeCompare(nameB)
    })
    return rows
  }, [breadthSort, latestBreadthRows, pinnedSet])
  useEffect(() => {
    if (!searchQuery.trim()) return
    if (activeTab === 'results') return
    const basePath = pathname || window.location.pathname
    if (!basePath.startsWith('/screener')) return
    const params = new URLSearchParams(searchParams.toString())
    params.set('tab', 'results')
    params.delete('views')
    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl, { scroll: false })
  }, [searchQuery, activeTab, pathname, router, searchParams])

  const compare = useCompare()
  const screenerMethodology = useScreenerMethodology()

  const handleStockSelect = (nextSymbol: string) => {
    const normalized = (nextSymbol || '').trim().toUpperCase()
    if (!normalized) return
    rememberTickerOrigin('screener')
    router.push(`/ticker/${encodeURIComponent(normalized)}`, { scroll: false })
  }

  const openSymbolSetups = (nextSymbol: string) => {
    const normalized = (nextSymbol || '').trim().toUpperCase()
    if (!normalized) return
    router.push(`/screener?symbol=${encodeURIComponent(normalized)}`)
  }

  const handlePrimarySymbolAction = (symbol: string) => {
    const normalized = (symbol || '').trim().toUpperCase()
    if (!normalized) return
    handleStockSelect(normalized)
  }

  const movementDriverLabel = (item: ScreenerChangeItem): string | null => {
    const raw = (item?.source || '').trim()
    if (!raw) return null

    const cleaned = raw.startsWith('RA-') ? raw.slice(3) : raw
    const parts = cleaned.split('-').map((p) => p.trim()).filter(Boolean)
    const driver = parts.length >= 2 ? parts.slice(1).join(' ') : cleaned

    const spaced = driver
      .replace(/_/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/([A-Za-z])([0-9])/g, '$1 $2')
      .replace(/([0-9])([A-Za-z])/g, '$1 $2')
      .replace(/\s+/g, ' ')
      .trim()

    return spaced || null
  }

  // Batch AI previews for visible symbols
  const symbols = Array.from(new Set(filteredItems.map(it => it.symbol))).filter(Boolean)
  const { data: previews } = useQuery({
    queryKey: ['ai-preview-batch', symbols.join(',')],
    queryFn: () => api.getAiPreviews(symbols),
    enabled: symbols.length > 0,
    staleTime: FIVE_MIN_MS,
  })

  const toggleRowExpanded = useCallback((symbol: string) => {
    setExpandedRows((prev) => ({ ...prev, [symbol]: !prev[symbol] }))
  }, [])

  useEffect(() => {
    if (!filteredItems.length) {
      setExpandedRows({})
      return
    }
    const visible = new Set(filteredItems.map((item) => item.symbol))
    setExpandedRows((prev) => {
      const next: Record<string, boolean> = {}
      Object.entries(prev).forEach(([sym, open]) => {
        if (open && visible.has(sym)) next[sym] = true
      })
      return next
    })
  }, [filteredItems])

  // Styles dropdown options (latest snapshot)
  const { data: styleMeta } = useQuery({
    queryKey: ['screener-styles-meta', bias],
    queryFn: () => api.listScreenerStylesMeta({ bias }),
    staleTime: FIVE_MIN_MS,
  })
  const { data: styleMetaAll } = useQuery({
    queryKey: ['screener-styles-meta', 'all'],
    queryFn: () => api.listScreenerStylesMeta({ bias: 'all' }),
    staleTime: FIVE_MIN_MS,
  })

  const sourcePrefix = 'RA-'
  const stylesCacheKey = styles.length ? styles.slice().sort().join(',') : 'all'
  const { data: sourceMeta } = useQuery({
    queryKey: ['screener-sources-meta', sourcePrefix, stylesCacheKey],
    queryFn: () => api.listScreenerSourcesMeta({ prefix: sourcePrefix, styles }),
    staleTime: FIVE_MIN_MS,
  })

  const findStylesByKeywords = useCallback((keywords: string[]) => {
    const lowered = keywords.map((k) => k.toLowerCase())
    const pool = styleMetaAll?.length ? styleMetaAll : (styleMeta || [])
    return pool
      .filter((opt) => lowered.some((k) => opt.name.toLowerCase().includes(k)))
      .map((opt) => opt.name)
  }, [styleMeta, styleMetaAll])

  const applyScreenerPreset = useCallback((preset: 'high_consensus' | 'momentum' | 'earnings_momo') => {
    clearFilters()
    if (preset === 'high_consensus') {
      setAppearancesMin(3)
      setStylesMin(2)
      setSortBy('consensus_score')
      setSortOrder('desc')
    }
    if (preset === 'momentum') {
      const picks = findStylesByKeywords(['momo', 'momentum', 'breakout'])
      if (picks.length) {
        setStyles(picks)
        setStyleMatchAll(false)
      }
      setBias('bullish')
    }
    if (preset === 'earnings_momo') {
      const earnings = findStylesByKeywords(['earn', 'earnings', 'post'])
      const momo = findStylesByKeywords(['momo', 'momentum', 'breakout'])
      const intersection = earnings.filter((name) => momo.includes(name))
      const picks = intersection.length ? intersection : earnings.length ? earnings : momo
      if (picks.length) {
        setStyles(picks)
        setStyleMatchAll(false)
      }
      setBias('bullish')
    }
    setPage(1)
  }, [clearFilters, findStylesByKeywords])

  const screenerPresets = useMemo(() => ([
    {
      key: 'high-consensus',
      label: 'High consensus',
      description: 'Min appearances 3+, min styles 2+.',
      onApply: () => applyScreenerPreset('high_consensus'),
    },
    {
      key: 'momentum-breakouts',
      label: 'Momentum breakouts',
      description: 'Bullish momentum styles if available.',
      onApply: () => applyScreenerPreset('momentum'),
    },
    {
      key: 'earnings-post-momo',
      label: 'Earnings post-momo',
      description: 'Earnings + momentum style intersection when available.',
      onApply: () => applyScreenerPreset('earnings_momo'),
    },
  ]), [applyScreenerPreset])

  function handleHeaderSort(key: SortBy) {
    setPage(1)
    if (sortBy === key) {
      setSortOrder(prev => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(key)
      // Defaults: keep desc for numeric metrics; asc for symbol
      setSortOrder(key === 'symbol' ? 'asc' : 'desc')
    }
  }

  const exportBreadthCsv = () => {
    if (!sortedBreadthRows.length) return
    const header = ['Bias', 'Style', 'Entrants', 'Entrants %', 'Drops', 'Drops %', 'Net %', 'Net 5d Avg']
    const rows = sortedBreadthRows.map((row: any) => {
      const isFlow = useFlowBreadth
      const styleName = isFlow ? row.canonical_name : row.style_name
      const biasLabel = row.regime_bias || ''
      const netPct = isFlow ? row.net_pct_us_signed : row.net_pct_signed
      const netAvg = isFlow ? row.churn_pct : row.net_pct_avg_5d
      return [
        biasLabel,
        styleName,
        row.entered_count ?? 0,
        row.entered_pct ?? 0,
        row.dropped_count ?? 0,
        row.dropped_pct ?? 0,
        netPct ?? 0,
        netAvg ?? 0,
      ]
    })
    const csv = [header, ...rows]
      .map((row) =>
        row
          .map((value) => {
            const str = String(value ?? '')
            return `"${str.replace(/"/g, '""')}"`
          })
          .join(',')
      )
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `screener-breadth-${formatEasternDate(new Date())}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader
        title="Screener"
        subtitle="Pre-built screens for swing trading. Updated nightly."
        contextBadges={headerContextBadges}
        primaryAction={<PrimaryCtaLink href="/rankings">Go to Rankings</PrimaryCtaLink>}
        secondaryActions={[
          (
            <Button
              key="screener-methodology"
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 rounded-full px-2 text-xs font-semibold text-muted-foreground hover:bg-secondary/40 hover:text-foreground"
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                screenerMethodology.open()
              }}
            >
              Methodology
            </Button>
          ),
          <SavedViewsButton key="screener-saved" onClick={openViews} />,
          (
            <TooltipCopy key="screener-copy" tooltipKey="global.share">
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
        tabs={(
          <div className="space-y-2">
            <ScreenerTabs activeTab={activeTab} onPrefetch={prefetchTab} />
            <div className="rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2 text-xs font-medium text-muted-foreground">
              {tabDescriptor}
            </div>
          </div>
        )}
        activeChips={(
          <div className="rounded-2xl border border-outline/12 bg-background/90 p-3 shadow-sm backdrop-blur">
            <ActiveFilterChips
              chips={activeFilterChips.map((chip) => ({
                ...chip,
                onRemove: chip.onRemove
                  ? () => {
                      chip.onRemove?.()
                      setPage(1)
                    }
                  : undefined,
              }))}
              onClearAll={clearFilters}
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
            {screenerPresets.length ? (
              <div className="mt-3 space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Filter presets</div>
                <div className="flex flex-wrap gap-2">
                  {screenerPresets.map((preset) => (
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
                storageKey={SCREENER_SAVED_VIEWS_KEY}
                currentQuery={currentSavedViewQuery}
                buildUrlForQuery={buildSavedViewUrlForQuery}
                buildUrlForView={buildSavedViewUrlForView}
                onLoad={applySavedView}
                savePath={savedViewsBasePath}
                namePlaceholder="e.g., Bullish + top styles"
                helperText="Saved Views store the current URL filters so you can reuse the same triage screen daily."
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
        <aside className={cn('space-y-6 lg:sticky lg:top-24', filtersCollapsed && 'lg:hidden')}>
          <Card className="border-outline/8">
            <CardHeader className="relative gap-1 pb-2">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="flex items-center gap-2 text-lg">
                  <FilterIcon className="h-4 w-4" />
                  Active Filters
                </CardTitle>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground lg:hidden"
                    onClick={() => setMobileFiltersOpen(prev => !prev)}
                    aria-expanded={mobileFiltersOpen}
                    aria-controls="screener-filters"
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
                Only screened stocks are shown.
              </CardDescription>
            </CardHeader>
            <CardContent className="relative">
              <div className={cn('space-y-1.5 lg:hidden', mobileFiltersOpen ? 'hidden' : 'block')}>
                <label
                  className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                  htmlFor="screenerSymbolMobile"
                >
                  Search
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="screenerSymbolMobile"
                    type="search"
                    placeholder="Symbol or company"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="h-9 w-full flex-1 rounded-md border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    onClick={() => openSymbolSetups(tickerCandidate)}
                    disabled={!tickerCandidate}
                    className="h-9 shrink-0 rounded-md border border-border/60 bg-background px-3 text-sm font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                    title={tickerCandidate ? `Open ${tickerCandidate} setup hits` : 'Type a ticker like NVDA'}
                  >
                    Setup hits
                  </button>
                </div>
              </div>
              <div
                id="screener-filters"
                className={`${mobileFiltersOpen ? 'grid' : 'hidden'} gap-4 lg:grid`}
              >
                <FilterSidebar>
                  <div className="space-y-1.5">
                    <label className="sr-only" htmlFor="screenerSymbol">Search</label>
                    <div className="flex items-center gap-2">
                      <input
                        id="screenerSymbol"
                        placeholder="Symbol or company"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="h-9 w-full flex-1 rounded-md border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        autoComplete="off"
                      />
                      <button
                        type="button"
                        onClick={() => openSymbolSetups(tickerCandidate)}
                        disabled={!tickerCandidate}
                        className="h-9 shrink-0 rounded-md border border-border/60 bg-background px-3 text-sm font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                        title={tickerCandidate ? `Open ${tickerCandidate} setup hits` : 'Type a ticker like NVDA'}
                      >
                        Setup hits
                      </button>
                    </div>
                  </div>

                  <FilterGroup
                    title="Key dropdowns"
                    description="Styles and screener sources."
                    titleAddon={(
                      <InfoTooltipButton
                        label="Styles & screens"
                        description="Styles describe the trading intent (momentum, pullback, mean-reversion). Screens are the named scanners used to build each style."
                        learnMore={{ label: 'View screener definitions', onClick: () => screenerMethodology.open() }}
                        iconSize="h-3.5 w-3.5"
                        buttonClassName="text-muted-foreground hover:text-foreground"
                        contentClassName="max-w-xs px-3 py-2 text-xs leading-relaxed"
                      />
                    )}
                  >
                    <div className="space-y-2">
                      <MultiSelect
                        label="Styles"
                        labelClassName="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                        options={styleMeta}
                        value={styles}
                        onChange={setStyles}
                      />
                      <label className="flex items-center gap-2 text-xs text-muted-foreground">
                        <input type="checkbox" checked={styleMatchAll} onChange={(e) => setStyleMatchAll(e.target.checked)} />
                        Match all selected styles
                      </label>
                    </div>
                    <div className="space-y-2">
                      <MultiSelect
                        label="Screens"
                        labelClassName="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                        options={sourceMeta}
                        value={sources}
                        onChange={setSources}
                      />
                      <label className="flex items-center gap-2 text-xs text-muted-foreground">
                        <input type="checkbox" checked={sourceMatchAll} onChange={(e) => setSourceMatchAll(e.target.checked)} />
                        Match all selected sources
                      </label>
                    </div>
                  </FilterGroup>

                  <FilterGroup title="Ranges" description="Minimum appearance thresholds.">
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
                      <div className="space-y-1.5">
                        <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground" htmlFor="screenerAppearances">Min Appearances</label>
                        <input
                          id="screenerAppearances"
                          type="number"
                          min={0}
                          value={appearancesMin}
                          onChange={(e) => setAppearancesMin(Number(e.target.value) || 0)}
                          className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground" htmlFor="screenerStyles">Min Styles</label>
                        <input
                          id="screenerStyles"
                          type="number"
                          min={0}
                          value={stylesMin}
                          onChange={(e) => setStylesMin(Number(e.target.value) || 0)}
                          className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      </div>
                    </div>
                  </FilterGroup>

                  <FilterGroup title="Bias">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        aria-pressed={bias === 'all'}
                        onClick={() => setBias('all')}
                        className={`inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                          bias === 'all'
                            ? 'bg-primary text-primary-foreground shadow-sm'
                            : 'bg-muted text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        All
                      </button>
                      <button
                        type="button"
                        aria-pressed={bias === 'bullish'}
                        onClick={() => setBias('bullish')}
                        className={`inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                          bias === 'bullish'
                            ? 'bg-primary text-primary-foreground shadow-sm'
                            : 'bg-muted text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        Bullish
                      </button>
                      <button
                        type="button"
                        aria-pressed={bias === 'bearish'}
                        onClick={() => setBias('bearish')}
                        className={`inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                          bias === 'bearish'
                            ? 'bg-primary text-primary-foreground shadow-sm'
                            : 'bg-muted text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        Bearish
                      </button>
                    </div>
                  </FilterGroup>
                </FilterSidebar>
              </div>
            </CardContent>
          </Card>
        </aside>

        <main className="mt-6 space-y-6 lg:mt-0">
          <section ref={resultsTopRef} id="screener-results-top" className="space-y-4">
            {activeTab === 'changes' && (
              <Card className="border-outline/8">
                <CardHeader className="relative">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1">
                      <CardTitle>Movements</CardTitle>
                      {changesError ? (
                        <InlineError message="Couldn't load movements." onRetry={() => void refetchChanges()} />
                      ) : (
                        <CardDescription>
                          Confirmed changes after a 3-trading-day window{latestChangeDate ? ` · ${formatDate(latestChangeDate)}` : ''}
                        </CardDescription>
                      )}
                      <DataFreshness asOf={latestChangeDate ?? null} cadence="Nightly" />
                    </div>
                  </div>

                  <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
                    <div className="rounded-2xl border border-outline/10 bg-secondary/10 px-3 py-2 shadow-sm">
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Window</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground">3 trading days</div>
                    </div>
                    <div className="rounded-2xl border border-outline/10 bg-secondary/10 px-3 py-2 shadow-sm">
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Universe</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground">
                        {resultsLoading ? 'Loading…' : `${total.toLocaleString()} symbols`}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => openMovementResults('entered')}
                      disabled={enteredDisabled}
                      className={cn(
                        'group rounded-2xl border border-outline/10 bg-card px-3 py-2 text-left shadow-sm transition',
                        enteredDisabled
                          ? 'cursor-not-allowed opacity-60'
                          : 'hover:-translate-y-[1px] hover:border-outline/16 hover:shadow-md',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                      )}
                      aria-label="View results list for new entrants"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          New entrants
                        </div>
                        <div className="text-sm font-semibold text-foreground tabular-nums">
                          {changesLoading ? '—' : enteredCount}
                        </div>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] font-medium text-muted-foreground">
                        {enteredDisabled ? (
                          <span>
                            {changesLoading
                              ? 'Loading movements…'
                              : changesError
                                ? 'Movements unavailable.'
                                : movementCardEmptyText('entered')}
                          </span>
                        ) : (
                          <>
                            <span className="group-hover:text-foreground">View list</span>
                            <button
                              type="button"
                              className="rounded-full border border-outline/10 bg-background/70 px-2 py-0.5 font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                openTriage('entered')
                              }}
                              aria-label="Open triage modal for new entrants"
                            >
                              Triage
                            </button>
                          </>
                        )}
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => openMovementResults('reentered')}
                      disabled={reenteredDisabled}
                      className={cn(
                        'group rounded-2xl border border-outline/10 bg-card px-3 py-2 text-left shadow-sm transition',
                        reenteredDisabled
                          ? 'cursor-not-allowed opacity-60'
                          : 'hover:-translate-y-[1px] hover:border-outline/16 hover:shadow-md',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                      )}
                      aria-label="View results list for re-entries"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          Re-entries
                        </div>
                        <div className="text-sm font-semibold text-foreground tabular-nums">
                          {changesLoading ? '—' : reenteredCount}
                        </div>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] font-medium text-muted-foreground">
                        {reenteredDisabled ? (
                          <span>
                            {changesLoading
                              ? 'Loading movements…'
                              : changesError
                                ? 'Movements unavailable.'
                                : movementCardEmptyText('reentered')}
                          </span>
                        ) : (
                          <>
                            <span className="group-hover:text-foreground">View list</span>
                            <button
                              type="button"
                              className="rounded-full border border-outline/10 bg-background/70 px-2 py-0.5 font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                openTriage('reentered')
                              }}
                              aria-label="Open triage modal for re-entries"
                            >
                              Triage
                            </button>
                          </>
                        )}
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => openMovementResults('dropped')}
                      disabled={droppedDisabled}
                      className={cn(
                        'group rounded-2xl border border-outline/10 bg-card px-3 py-2 text-left shadow-sm transition',
                        droppedDisabled
                          ? 'cursor-not-allowed opacity-60'
                          : 'hover:-translate-y-[1px] hover:border-outline/16 hover:shadow-md',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                      )}
                      aria-label="View results list for drops"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          Drops
                        </div>
                        <div className="text-sm font-semibold text-foreground tabular-nums">
                          {changesLoading ? '—' : droppedCount}
                        </div>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] font-medium text-muted-foreground">
                        {droppedDisabled ? (
                          <span>
                            {changesLoading
                              ? 'Loading movements…'
                              : changesError
                                ? 'Movements unavailable.'
                                : movementCardEmptyText('dropped')}
                          </span>
                        ) : (
                          <>
                            <span className="group-hover:text-foreground">View list</span>
                            <button
                              type="button"
                              className="rounded-full border border-outline/10 bg-background/70 px-2 py-0.5 font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                openTriage('dropped')
                              }}
                              aria-label="Open triage modal for drops"
                            >
                              Triage
                            </button>
                          </>
                        )}
                      </div>
                    </button>
                    <div className="rounded-2xl border border-outline/10 bg-secondary/10 px-3 py-2 shadow-sm">
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Net</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground tabular-nums">
                        {formatSigned(movementsNet, 0)}
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="relative">
                  {changesLoading ? (
                    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                      {[...Array(3)].map((_, idx) => (
                        <div key={idx} className="space-y-3">
                          <Skeleton className="h-5 w-32" />
                          <Skeleton className="h-20 w-full" />
                        </div>
                      ))}
                    </div>
                  ) : changeItems.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-outline/12 bg-secondary/10 p-4 text-sm text-muted-foreground">
                      <div>No confirmed movements in the last {movementWindowLabel}. Try increasing the window.</div>
                      {showExpandWindowAction ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="mt-3 h-9 rounded-full px-4 text-xs"
                          onClick={() => expandMovementWindow(10)}
                        >
                          Expand window to 10 days
                        </Button>
                      ) : null}
                    </div>
                  ) : (
                    <>
                      <div className="hidden lg:grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                        <ChangeColumn
                          title="New Entrants"
                          items={enteredChanges}
                          emptyLabel={movementColumnEmptyLabels.entered}
                          driverLabel={movementDriverLabel}
                          onPrimaryAction={handlePrimarySymbolAction}
                        />
                        <ChangeColumn
                          title="Re-entries"
                          items={reenteredChanges}
                          emptyLabel={movementColumnEmptyLabels.reentered}
                          driverLabel={movementDriverLabel}
                          onPrimaryAction={handlePrimarySymbolAction}
                        />
                        <ChangeColumn
                          title="Confirmed Drops"
                          items={droppedChanges}
                          emptyLabel={movementColumnEmptyLabels.dropped}
                          driverLabel={movementDriverLabel}
                          onPrimaryAction={handlePrimarySymbolAction}
                        />
                      </div>
                      <div className="lg:hidden space-y-3">
                        <MobileChangeSection
                          title="New Entrants"
                          items={enteredChanges}
                          emptyLabel={movementColumnEmptyLabels.entered}
                          driverLabel={movementDriverLabel}
                          onPrimaryAction={handlePrimarySymbolAction}
                        />
                        <MobileChangeSection
                          title="Re-entries"
                          items={reenteredChanges}
                          emptyLabel={movementColumnEmptyLabels.reentered}
                          driverLabel={movementDriverLabel}
                          onPrimaryAction={handlePrimarySymbolAction}
                        />
                        <MobileChangeSection
                          title="Confirmed Drops"
                          items={droppedChanges}
                          emptyLabel={movementColumnEmptyLabels.dropped}
                          driverLabel={movementDriverLabel}
                          onPrimaryAction={handlePrimarySymbolAction}
                        />
                      </div>
                    </>
                  )}

                  <Dialog open={triageOpen} onOpenChange={setTriageOpen}>
                    <DialogContent
                      className={cn(
                        'fixed inset-0 left-0 top-0 z-50 grid h-[100dvh] w-screen max-w-none translate-x-0 translate-y-0 gap-0 rounded-none border-0 bg-background p-0',
                        'lg:inset-auto lg:bottom-4 lg:right-4 lg:top-16 lg:h-auto lg:max-h-[calc(100dvh-6rem)] lg:w-[520px] lg:max-w-[min(520px,calc(100vw-2rem))] lg:rounded-2xl lg:border lg:p-0',
                      )}
                      hideClose
                    >
                      <DialogHeader className="flex flex-row items-center justify-between border-b border-border/60 px-4 py-3">
                        <DialogTitle className="text-base font-semibold">
                          Triage · {triageTitle}
                        </DialogTitle>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 rounded-full border border-outline/10 px-3 text-xs"
                          onClick={() => setTriageOpen(false)}
                        >
                          Close
                        </Button>
                      </DialogHeader>

                      <div className="min-h-0 overflow-y-auto px-4 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setTriageFocus('entered')}
                            className={cn(
                              'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold transition',
                              triageFocus === 'entered'
                                ? 'border-primary/40 bg-primary/10 text-foreground'
                                : 'border-outline/10 bg-card text-muted-foreground hover:border-outline/16 hover:text-foreground',
                            )}
                          >
                            Entrants <span className="tabular-nums text-muted-foreground">{enteredChanges.length}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setTriageFocus('reentered')}
                            className={cn(
                              'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold transition',
                              triageFocus === 'reentered'
                                ? 'border-primary/40 bg-primary/10 text-foreground'
                                : 'border-outline/10 bg-card text-muted-foreground hover:border-outline/16 hover:text-foreground',
                            )}
                          >
                            Re-entries <span className="tabular-nums text-muted-foreground">{reenteredChanges.length}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setTriageFocus('dropped')}
                            className={cn(
                              'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold transition',
                              triageFocus === 'dropped'
                                ? 'border-primary/40 bg-primary/10 text-foreground'
                                : 'border-outline/10 bg-card text-muted-foreground hover:border-outline/16 hover:text-foreground',
                            )}
                          >
                            Drops <span className="tabular-nums text-muted-foreground">{droppedChanges.length}</span>
                          </button>

                          <div className="ml-auto hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
                            <span className="rounded-full border border-outline/10 bg-secondary/10 px-2 py-1 font-semibold">
                              Window 3d
                            </span>
                            <span className="rounded-full border border-outline/10 bg-secondary/10 px-2 py-1 font-semibold">
                              {resultsLoading ? 'Universe…' : `${total.toLocaleString()} symbols`}
                            </span>
                          </div>
                        </div>

                        {triageItems.length === 0 ? (
                          <div className="mt-4 rounded-2xl border border-dashed border-outline/12 bg-secondary/10 p-4 text-sm text-muted-foreground">
                            No confirmed {triageTitle.toLowerCase()} in the last {movementWindowLabel}. Try increasing the window.
                          </div>
                        ) : (
                          <div className="mt-4 space-y-2">
                            {triageItems.map((item) => {
                              const sym = (item.symbol || '').trim().toUpperCase()
                              const delta = item.rank_delta
                              const deltaToneClass =
                                delta == null || !Number.isFinite(delta)
                                  ? 'text-muted-foreground'
                                  : delta > 0
                                    ? 'text-status-success'
                                    : delta < 0
                                      ? 'text-status-danger'
                                      : 'text-muted-foreground'
                              const deltaIcon =
                                delta != null && Number.isFinite(delta)
                                  ? delta > 0
                                    ? <ArrowUpIcon className="h-3.5 w-3.5" aria-hidden="true" />
                                    : delta < 0
                                      ? <ArrowDownIcon className="h-3.5 w-3.5" aria-hidden="true" />
                                      : null
                                  : null
                              const driver = movementDriverLabel(item)
                              const style = (item.style || '').trim()
                              return (
                                <div
                                  key={`${item.change_date}:${item.change_type}:${sym}:${item.source}`}
                                  className={cn(
                                    'group rounded-2xl border border-outline/10 bg-card p-3 shadow-sm transition',
                                    'hover:-translate-y-[1px] hover:border-outline/16 hover:shadow-md',
                                  )}
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <button
                                      type="button"
                                      onClick={() => handlePrimarySymbolAction(sym)}
                                      className="min-w-0 flex-1 text-left"
                                      aria-label={`Open ${sym}`}
                                    >
                                      <div className="flex items-center gap-2">
                                        <div className="text-sm font-semibold text-foreground">{sym}</div>
                                        {item.regime_bias ? (
                                          <Badge variant={item.regime_bias === 'Bearish' ? 'danger' : 'success'} className="text-xs font-semibold">
                                            {item.regime_bias}
                                          </Badge>
                                        ) : null}
                                      </div>
                                      <div className="mt-0.5 truncate text-xs text-muted-foreground">{item.company_name || '-'}</div>
                                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] font-semibold text-muted-foreground">
                                        {style ? (
                                          <span className="rounded-full border border-outline/10 bg-secondary/10 px-2 py-1">
                                            {style}
                                          </span>
                                        ) : null}
                                        {driver ? (
                                          <span className="rounded-full border border-outline/10 bg-secondary/10 px-2 py-1">
                                            {driver}
                                          </span>
                                        ) : null}
                                        <span className={cn('inline-flex items-center gap-1 rounded-full border border-outline/10 bg-secondary/10 px-2 py-1 tabular-nums', deltaToneClass)}>
                                          {deltaIcon}
                                          Rank Δ {formatSigned(item.rank_delta, 0)}
                                        </span>
                                        <span className="rounded-full border border-outline/10 bg-secondary/10 px-2 py-1 tabular-nums">
                                          Now {formatNumberValue(item.current_rank ?? null, 0)}
                                        </span>
                                        <span className="rounded-full border border-outline/10 bg-secondary/10 px-2 py-1 tabular-nums">
                                          Prev {formatNumberValue(item.previous_rank ?? null, 0)}
                                        </span>
                                      </div>
                                    </button>

                                    <div className="flex flex-col items-end gap-2">
                                      <CompareCheckbox symbol={sym} tooltipVariant="compact" />
                                      <div className="flex items-center gap-1.5">
                                        <button
                                          type="button"
                                          onClick={() => openSymbolSetups(sym)}
                                          className="rounded-full border border-border/60 bg-background/80 px-2 py-0.5 text-[11px] font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary"
                                          aria-label={`Open setup hits for ${sym}`}
                                        >
                                          Setup hits
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => handleStockSelect(sym)}
                                          className="rounded-full border border-border/60 bg-background/80 px-2 py-0.5 text-[11px] font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary"
                                          aria-label={`Open stock details for ${sym}`}
                                        >
                                          <ExternalLinkIcon className="h-3.5 w-3.5" aria-hidden />
                                        </button>
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    </DialogContent>
                  </Dialog>
                </CardContent>
              </Card>
            )}

            {activeTab === 'breadth' && (
              <Card className="border-outline/8">
                <CardHeader className="relative">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        <span>Market Breadth</span>
                        <TooltipCopyButton tooltipKey="screener.breadthFlow" iconSize="h-3 w-3" buttonClassName="text-muted-foreground/70" />
                      </CardTitle>
                      <CardDescription>
                        Daily share of symbols entering or leaving each style{latestBreadthDate ? ` · ${formatDate(latestBreadthDate)}` : ''}
                      </CardDescription>
                      <DataFreshness asOf={latestBreadthDate ?? null} cadence="Daily" />
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="inline-flex rounded-md border bg-muted/40 p-1 text-xs font-medium">
                        <button
                          type="button"
                          onClick={() => setBreadthMode('flow')}
                          className={`rounded-sm px-3 py-1 transition ${useFlow ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                          aria-pressed={useFlow}
                        >
                          Flow
                        </button>
                        <button
                          type="button"
                          onClick={() => setBreadthMode('legacy')}
                          className={`rounded-sm px-3 py-1 transition ${!useFlow ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                          aria-pressed={!useFlow}
                        >
                          Legacy
                        </button>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8 rounded-full px-3 text-[11px]"
                        onClick={exportBreadthCsv}
                        disabled={!sortedBreadthRows.length}
                      >
                        <DownloadIcon className="mr-1 h-3.5 w-3.5" aria-hidden />
                        Export CSV
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="relative">
                  {activeBreadthError ? (
                    <InlineError message="Couldn't load breadth." onRetry={() => void activeBreadthRefetch()} />
                  ) : activeBreadthLoading ? (
                    <div className="space-y-3">
                      {[...Array(4)].map((_, idx) => <Skeleton key={idx} className="h-14 w-full" />)}
                    </div>
                  ) : !latestBreadthRows.length ? (
                    <p className="text-sm text-muted-foreground">
                      No breadth data available for the current filters.
                      {useFlow && hasLegacyRows ? ' Flow breadth is still warming up-switch to Legacy to view the latest saved snapshot.' : ''}
                    </p>
                  ) : (
                    <div className="space-y-4">
                      {breadthSummary && (
                        <div className="flex flex-wrap items-center gap-4 rounded-md border bg-muted/40 p-3 text-sm">
                          <div>
                            <span className="text-muted-foreground">Entrants</span>
                            <div className="font-medium">
                              {breadthSummary.totalEntered.toLocaleString()} ({formatPct(breadthSummary.enteredShare || 0)})
                            </div>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Drops</span>
                            <div className="font-medium">
                              {breadthSummary.totalDropped.toLocaleString()} ({formatPct(breadthSummary.droppedShare || 0)})
                            </div>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Net vs 5-day</span>
                            <div className="font-medium flex items-center gap-2">
                              <TrendBadge value={breadthSummary.netPctWeighted} baseline={breadthSummary.netPctAvg5dWeighted} />
                            </div>
                          </div>
                          {useFlow && (
                            <p className="text-xs text-muted-foreground">
                              Flow uses canonical style shares; counts are approximations derived from universe size × share.
                            </p>
                          )}
                        </div>
                      )}
                      <div className="overflow-x-auto">
                        <DataTable className="data-table--sticky">
                          <thead>
                            <tr className="text-left text-muted-foreground">
                              <th className="py-2 pr-2">
                                <span className="sr-only">Pin</span>
                              </th>
                              <th className="py-2 pr-4">
                                <ColumnHeaderTooltip label="Bias" tooltipKey="screener.breadth.bias" />
                              </th>
                              <th className="py-2 pr-4">
                                <ColumnHeaderTooltip label="Style" tooltipKey="screener.breadth.style" />
                              </th>
                              <th className="py-2 pr-4">
                                <div className="inline-flex items-center gap-1">
                                  <button
                                    type="button"
                                    className="inline-flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground"
                                    onClick={() => handleBreadthSort('entered')}
                                  >
                                    Entrants
                                    {breadthSort.key === 'entered' ? <span>{breadthSort.dir === 'asc' ? '↑' : '↓'}</span> : null}
                                  </button>
                                  <TooltipCopyButton tooltipKey="screener.breadth.entrants" iconSize="h-3 w-3" buttonClassName="text-muted-foreground/70" />
                                </div>
                              </th>
                              <th className="py-2 pr-4">
                                <div className="inline-flex items-center gap-1">
                                  <button
                                    type="button"
                                    className="inline-flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground"
                                    onClick={() => handleBreadthSort('dropped')}
                                  >
                                    Drops
                                    {breadthSort.key === 'dropped' ? <span>{breadthSort.dir === 'asc' ? '↑' : '↓'}</span> : null}
                                  </button>
                                  <TooltipCopyButton tooltipKey="screener.breadth.drops" iconSize="h-3 w-3" buttonClassName="text-muted-foreground/70" />
                                </div>
                              </th>
                              <th className="py-2 pr-4">
                                <div className="inline-flex items-center gap-1">
                                  <button
                                    type="button"
                                    className="inline-flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground"
                                    onClick={() => handleBreadthSort('net')}
                                  >
                                    Net %
                                    {breadthSort.key === 'net' ? <span>{breadthSort.dir === 'asc' ? '↑' : '↓'}</span> : null}
                                  </button>
                                  <TooltipCopyButton tooltipKey="screener.breadth.net" iconSize="h-3 w-3" buttonClassName="text-muted-foreground/70" />
                                </div>
                              </th>
                              <th className="py-2 pr-4">
                                <ColumnHeaderTooltip label="Net 5d Avg" tooltipKey="screener.breadth.netAvg" />
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {sortedBreadthRows.map((row: any) => {
                              const isFlow = useFlowBreadth
                              const styleName = isFlow ? row.canonical_name : row.style_name
                              const biasLabel = row.regime_bias as ('Bullish'|'Bearish'|undefined)
                              const pinKey = `${biasLabel || 'Neutral'}:${styleName}`
                              const key = isFlow ? `${styleName}-${row.change_date}` : String(row.style_key)
                              const netVal = isFlow ? (row.net_pct_us_signed ?? 0) : (row.net_pct_signed ?? 0)
                              const baseVal = isFlow ? (row.churn_pct_signed ?? 0) : (row.net_pct_avg_5d_signed ?? 0)
                              const tailPct = isFlow ? (row.churn_pct ?? 0) : (row.net_pct_avg_5d ?? 0)
                              return (
                                <ClickableTableRow
                                  key={key}
                                  onActivate={() => setBreadthDrilldown({ style: styleName, bias: biasLabel ?? null })}
                                  aria-label={`Open breadth drilldown for ${styleName}`}
                                >
                                  <td className="py-2 pr-2 align-middle">
                                    <button
                                      type="button"
                                      onClick={(event) => {
                                        event.preventDefault()
                                        event.stopPropagation()
                                        toggleBreadthPin(pinKey)
                                      }}
                                      className={cn(
                                        'inline-flex h-7 w-7 items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition',
                                        pinnedSet.has(pinKey)
                                          ? 'border-primary/40 bg-primary/10 text-primary'
                                          : 'hover:border-outline/20 hover:text-foreground'
                                      )}
                                      aria-label={pinnedSet.has(pinKey) ? `Unpin ${styleName}` : `Pin ${styleName}`}
                                    >
                                      <PinIcon className="h-3.5 w-3.5" aria-hidden />
                                    </button>
                                  </td>
                                  <td className="py-2 pr-4 align-middle">
                                    {biasLabel ? (
                                      <Badge variant={biasLabel === 'Bearish' ? 'danger' : 'success'} className="text-xs font-semibold">
                                        {biasLabel}
                                      </Badge>
                                    ) : (
                                      <span className="text-xs text-muted-foreground">-</span>
                                    )}
                                  </td>
                                  <td className="py-2 pr-4 font-medium">{styleName}</td>
                                  <td className="py-2 pr-4">{Number(row.entered_count || 0).toLocaleString()} ({formatPct(row.entered_pct)})</td>
                                  <td className="py-2 pr-4">{Number(row.dropped_count || 0).toLocaleString()} ({formatPct(row.dropped_pct)})</td>
                                  <td className="py-2 pr-4">
                                    <TrendBadge value={netVal} baseline={baseVal} compact />
                                  </td>
                                  <td className="py-2 pr-4">{formatPct(tailPct)}</td>
                                </ClickableTableRow>
                              )
                            })}
                          </tbody>
                        </DataTable>
                      </div>
                    </div>
                  )}

                  <DataFooter
                    source="Internal model"
                    links={[{ label: 'Methodology', href: '/about/screeners' }]}
                  />

                  <Dialog open={Boolean(breadthDrilldown)} onOpenChange={(next) => (!next ? setBreadthDrilldown(null) : null)}>
                    <DialogContent className="max-w-3xl">
                      <DialogHeader className="flex flex-row items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <DialogTitle className="text-base">Breadth drilldown</DialogTitle>
                          <div className="text-sm text-muted-foreground">
                            {(breadthDrilldown?.style || '').trim()}
                            {breadthDrilldown?.bias ? ` · ${breadthDrilldown.bias}` : ''}
                            {latestChangeDate ? ` · ${formatEasternDate(latestChangeDate)}` : ''}
                          </div>
                        </div>
                        <Button type="button" variant="outline" size="sm" className="h-9 rounded-full px-4" onClick={() => setBreadthDrilldown(null)}>
                          Close
                        </Button>
                      </DialogHeader>

                      <div className="grid gap-4 sm:grid-cols-2">
                        <div className="rounded-2xl border border-outline/10 bg-secondary/10 p-3">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                              Entrants
                            </div>
                            {breadthDrilldown?.style ? (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-8 rounded-full px-3 text-xs"
                                onClick={() => {
                                  const style = breadthDrilldown.style
                                  setBreadthDrilldown(null)
                                  openMovementResults('entrants', { style })
                                }}
                              >
                                View list
                              </Button>
                            ) : null}
                          </div>
                          <div className="mt-2 space-y-2">
                            {(breadthDrillItems?.entrants ?? []).length ? (
                              (breadthDrillItems!.entrants ?? []).slice(0, 40).map((it) => {
                                const sym = (it.symbol || '').trim().toUpperCase()
                                const focusReturnId = `screener-breadth-entrant-${sym}`
                                return (
                                  <button
                                    key={`${it.change_type}:${sym}:${it.source}`}
                                    type="button"
                                    className="flex w-full items-center justify-between gap-2 rounded-xl border border-outline/10 bg-card px-3 py-2 text-left transition hover:border-outline/16"
                                    onClick={() => {
                                      writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                      setBreadthDrilldown(null)
                                      handlePrimarySymbolAction(sym)
                                    }}
                                    id={focusReturnId}
                                    aria-label={`Open ${sym}`}
                                  >
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2">
                                        <span className="font-semibold text-foreground">{sym}</span>
                                        <Badge variant="secondary" className="text-[10px] font-semibold">
                                          {it.change_type === 'reentered' ? 'Re-entered' : 'New'}
                                        </Badge>
                                      </div>
                                      <div className="truncate text-xs text-muted-foreground">{it.company_name || '-'}</div>
                                    </div>
                                    <CompareCheckbox symbol={sym} tooltipVariant="compact" />
                                  </button>
                                )
                              })
                            ) : (
                              <div className="rounded-xl border border-dashed border-outline/12 bg-card p-3 text-sm text-muted-foreground">
                                No entrants for this style on the latest change date.
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="rounded-2xl border border-outline/10 bg-secondary/10 p-3">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                              Drops
                            </div>
                            {breadthDrilldown?.style ? (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-8 rounded-full px-3 text-xs"
                                onClick={() => {
                                  const style = breadthDrilldown.style
                                  setBreadthDrilldown(null)
                                  openMovementResults('dropped', { style })
                                }}
                              >
                                View list
                              </Button>
                            ) : null}
                          </div>
                          <div className="mt-2 space-y-2">
                            {(breadthDrillItems?.drops ?? []).length ? (
                              (breadthDrillItems!.drops ?? []).slice(0, 40).map((it) => {
                                const sym = (it.symbol || '').trim().toUpperCase()
                                const focusReturnId = `screener-breadth-drop-${sym}`
                                return (
                                  <button
                                    key={`${it.change_type}:${sym}:${it.source}`}
                                    type="button"
                                    className="flex w-full items-center justify-between gap-2 rounded-xl border border-outline/10 bg-card px-3 py-2 text-left transition hover:border-outline/16"
                                    onClick={() => {
                                      writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                      setBreadthDrilldown(null)
                                      handlePrimarySymbolAction(sym)
                                    }}
                                    id={focusReturnId}
                                    aria-label={`Open ${sym}`}
                                  >
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2">
                                        <span className="font-semibold text-foreground">{sym}</span>
                                        <Badge variant="secondary" className="text-[10px] font-semibold">Drop</Badge>
                                      </div>
                                      <div className="truncate text-xs text-muted-foreground">{it.company_name || '-'}</div>
                                    </div>
                                    <CompareCheckbox symbol={sym} tooltipVariant="compact" />
                                  </button>
                                )
                              })
                            ) : (
                              <div className="rounded-xl border border-dashed border-outline/12 bg-card p-3 text-sm text-muted-foreground">
                                No drops for this style on the latest change date.
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </DialogContent>
                  </Dialog>
                </CardContent>
              </Card>
            )}
            {activeTab === 'results' && (
              <Card className="border-outline/8">
                <CardHeader className="relative">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1">
                      <CardTitle>Results</CardTitle>
                      {isError ? (
                        <InlineError message="Couldn't load results." onRetry={() => void refetchScreener()} />
                      ) : (
                        <CardDescription>
                          {movementFilter ? (
                            <>
                              {movementListTitle ? `${movementListTitle} · ` : ''}
                              {movementListItems.length.toLocaleString()} symbols
                              {latestChangeDate ? ` · ${formatEasternDate(latestChangeDate)}` : ''}
                            </>
                          ) : total ? (
                            <>
                              Showing {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} of {total}
                              {countDelta ? (
                                <span className="ml-2 inline-flex items-center">
                                  <Badge variant="secondary" className="text-[11px]">
                                    {countDelta}
                                  </Badge>
                                </span>
                              ) : null}
                            </>
                          ) : (
                            <>No results</>
                          )}
                        </CardDescription>
                      )}
                      <DataFreshness
                        asOf={movementFilter ? latestChangeDate ?? null : latestAsOf ?? null}
                        cadence="Nightly"
                      />
                    </div>
                    {movementFilter ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-9 rounded-full px-4 text-xs"
                          onClick={clearMovementResults}
                        >
                          Clear movement
                        </Button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <div className="inline-flex items-center rounded-full border border-outline/10 bg-card p-1" aria-label="Results view mode">
                          <button
                            type="button"
                            className={cn(
                              'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
                              resultsView === 'table'
                                ? 'bg-background text-foreground shadow-sm'
                                : 'text-muted-foreground hover:text-foreground',
                            )}
                            onClick={() => setResultsView('table')}
                            aria-pressed={resultsView === 'table'}
                          >
                            <Table2Icon className="h-4 w-4" aria-hidden />
                            <span className="hidden sm:inline">Compact</span>
                          </button>
                          <button
                            type="button"
                            className={cn(
                              'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
                              resultsView === 'cards'
                                ? 'bg-background text-foreground shadow-sm'
                                : 'text-muted-foreground hover:text-foreground',
                            )}
                            onClick={() => setResultsView('cards')}
                            aria-pressed={resultsView === 'cards'}
                          >
                            <LayoutGridIcon className="h-4 w-4" aria-hidden />
                            <span className="hidden sm:inline">Cards</span>
                          </button>
                        </div>
                        {!isMobile ? (
                          <DensityToggle value={density} onChange={setDensity} compactLabels />
                        ) : null}
                        {!isMobile && resultsView === 'table' ? (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-9 rounded-full px-4 text-xs"
                            onClick={() => setShowSparklines((prev) => !prev)}
                          >
                            {showSparklines ? 'Sparklines on' : 'Sparklines off'}
                          </Button>
                        ) : null}
                        <span className="mr-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Sort</span>
                        <select
                          value={sortBy}
                          onChange={(e) => { setPage(1); setSortBy(e.target.value as SortBy) }}
                          className="h-9 rounded-md border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring sm:text-sm"
                        >
                          <option value="consensus_score">Consensus score</option>
                          <option value="appearances">Appearances (consensus count)</option>
                          <option value="styles_distinct">Styles</option>
                          <option value="sources_distinct">Sources</option>
                          <option value="rank_best">Best rank</option>
                          <option value="min_style_rank_pct">Min style %</option>
                          <option value="symbol">Symbol</option>
                        </select>
                        <button
                          className="rounded-md border px-2 py-1 hover:bg-accent"
                          title="Toggle sort order"
                          onClick={() => { setPage(1); setSortOrder(p => p === 'asc' ? 'desc' : 'asc') }}
                        >
                          {sortOrder === 'asc' ? 'Asc ↑' : 'Desc ↓'}
                        </button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-9 rounded-full px-4 text-sm"
                          onClick={() => setResultsColumnsOpen(true)}
                        >
                          Columns
                        </Button>
                        <button className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>Prev</button>
                        <span className="text-xs sm:text-sm">Page {page} / {totalPages}</span>
                        <button className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>Next</button>
                      </div>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="relative">
                  {movementFilter ? (
                    changesLoading || changesError || movementListItems.length === 0 ? (
                      <DataStateWrapper
                        status={changesLoading ? 'loading' : changesError ? 'error' : 'empty'}
                        context="screener-movements"
                        loadingLabel="Loading Screener Movements…"
                        title={changesError ? 'Data temporarily unavailable' : 'No results'}
                        message={
                          changesError
                            ? 'Failed to load movement results.'
                            : movementEmptyMessage
                        }
                        lastUpdated={lastUpdatedLabel}
                        filters={activeFilterChips.map((chip) => ({ key: chip.key, label: chip.label, onRemove: chip.onRemove }))}
                        onClearFilters={activeFilterChips.length ? relaxMovementFilters : undefined}
                        clearFiltersLabel="Relax filters"
                        tips={[
                          `Expand the movement window or view drops to gauge rotation.`,
                          'Reduce min appearances or style counts to widen the bucket.',
                        ]}
                        primaryAction={showExpandWindowAction ? {
                          label: 'Expand window to 10 days',
                          onClick: () => expandMovementWindow(10),
                          variant: 'outline',
                        } : undefined}
                        secondaryAction={movementFilter !== 'dropped' ? {
                          label: 'View drops',
                          onClick: () => openMovementResults('dropped', movementStyle ? { style: movementStyle } : undefined),
                          variant: 'outline',
                        } : undefined}
                        onRetry={changesError ? () => void refetchChanges() : undefined}
                        error={changesErrorRaw}
                      />
                    ) : (
                      <div className="relative overflow-x-auto rounded-2xl border border-border/60">
                        <DataTable className="data-table--sticky text-xs sm:text-sm">
                          <thead>
                            <tr className="text-left text-muted-foreground">
                              <th className="sticky top-0 left-0 z-20 w-9 border-b border-border/60 bg-background/90 py-2 pr-3 align-middle backdrop-blur">
                                <span className="sr-only">Compare</span>
                              </th>
                              <th className="sticky top-0 left-9 z-20 border-b border-border/60 bg-background/90 py-2 pr-3 align-middle backdrop-blur border-r border-border/60">
                                <ColumnHeaderTooltip label="Symbol" tooltipKey="screener.results.symbol" />
                              </th>
                              <th className="sticky top-0 z-10 border-b border-border/60 bg-background/90 py-2 pr-3 align-middle backdrop-blur">
                                <ColumnHeaderTooltip label="Company" tooltipKey="screener.results.company" />
                              </th>
                              <th className="sticky top-0 z-10 border-b border-border/60 bg-background/90 py-2 pr-3 align-middle backdrop-blur">
                                <ColumnHeaderTooltip label="Style" tooltipKey="screener.results.style" />
                              </th>
                              <th className="sticky top-0 z-10 border-b border-border/60 bg-background/90 py-2 pr-3 align-middle text-right backdrop-blur">
                                <div className="flex items-center justify-end gap-1">
                                  <span>Rank Δ</span>
                                  <TooltipCopyButton tooltipKey="screener.results.rankDelta" iconSize="h-3 w-3" buttonClassName="text-muted-foreground hover:text-foreground" />
                                </div>
                              </th>
                              <th className="sticky top-0 z-10 border-b border-border/60 bg-background/90 py-2 pr-3 align-middle text-right backdrop-blur">
                                <div className="flex items-center justify-end gap-1">
                                  <span>Now</span>
                                  <TooltipCopyButton tooltipKey="screener.results.rankNow" iconSize="h-3 w-3" buttonClassName="text-muted-foreground hover:text-foreground" />
                                </div>
                              </th>
                              <th className="sticky top-0 z-10 border-b border-border/60 bg-background/90 py-2 pr-3 align-middle text-right backdrop-blur">
                                <div className="flex items-center justify-end gap-1">
                                  <span>Prev</span>
                                  <TooltipCopyButton tooltipKey="screener.results.rankPrev" iconSize="h-3 w-3" buttonClassName="text-muted-foreground hover:text-foreground" />
                                </div>
                              </th>
                              <th className="sticky top-0 z-10 border-b border-border/60 bg-background/90 py-2 pr-4 align-middle backdrop-blur">
                                <ColumnHeaderTooltip label="Driver" tooltipKey="screener.results.driver" />
                              </th>
                              <th className="sticky top-0 z-10 w-9 border-b border-border/60 bg-background/90 py-2 pr-4 text-right align-middle backdrop-blur">
                                <span className="sr-only">Open</span>
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {movementListItems.map((item) => {
                              const sym = (item.symbol || '').trim().toUpperCase()
                              const focusReturnId = `screener-movement-row-${sym}`
                              const driver = movementDriverLabel(item)
                              return (
                                <ClickableTableRow
                                  key={`${item.change_type}:${sym}:${item.source}`}
                                  id={focusReturnId}
                                  onActivate={() => {
                                    writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                    handlePrimarySymbolAction(sym)
                                  }}
                                  selected={compare.symbols.includes(sym)}
                                  aria-label={`Open details for ${sym}`}
                                >
                                  <CompareCheckboxCell symbol={sym} cellClassName="sticky left-0 z-10 bg-card py-1.5 sm:py-2 pr-3 sm:pr-4" />
                                  <td className="sticky left-9 z-10 bg-card py-1.5 pr-3 font-semibold align-middle sm:py-2 sm:pr-4 border-r border-outline/10">{sym}</td>
                                  <td className="py-1.5 pr-3 max-w-[14rem] truncate align-middle sm:py-2 sm:pr-4" title={item.company_name || ''}>
                                    {item.company_name || '-'}
                                  </td>
                                  <td className="py-1.5 pr-3 align-middle sm:py-2 sm:pr-4">{(item.style || '').trim() || '-'}</td>
                                  <td className="py-1.5 pr-3 text-right align-middle tabular-nums sm:py-2 sm:pr-4">
                                    {formatSigned(item.rank_delta, 0)}
                                  </td>
                                  <td className="py-1.5 pr-3 text-right align-middle tabular-nums sm:py-2 sm:pr-4">
                                    {formatNumberValue(item.current_rank ?? null, 0)}
                                  </td>
                                  <td className="py-1.5 pr-3 text-right align-middle tabular-nums sm:py-2 sm:pr-4">
                                    {formatNumberValue(item.previous_rank ?? null, 0)}
                                  </td>
                                  <td className="py-1.5 pr-4 align-middle text-xs text-muted-foreground sm:py-2">
                                    {driver || '-'}
                                  </td>
                                  <td className="py-1.5 pr-4 align-middle text-right sm:py-2">
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <button
                                          type="button"
                                          onClick={(event) => {
                                            event.stopPropagation()
                                            writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                            handlePrimarySymbolAction(sym)
                                          }}
                                          className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                          aria-label={`Open details for ${sym}`}
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
                      </div>
                    )
                  ) : (
                    <>
                      {/* Server-side sorting active; no local sort warning needed */}
                      <Dialog open={resultsColumnsOpen} onOpenChange={setResultsColumnsOpen}>
                        <DialogContent className="max-w-[640px]">
                          <DialogHeader className="space-y-1">
                            <DialogTitle className="text-base">Result columns</DialogTitle>
                            <div className="text-sm text-muted-foreground">
                              Hide, reorder, or save your preferred column layouts. Saved in your browser and included in shared links.
                            </div>
                          </DialogHeader>

                          <div className="space-y-4">
                            <div className="rounded-lg border border-outline/10 bg-secondary/10 px-3 py-2 text-xs text-muted-foreground">
                              Pinned columns: Compare, Expand, Symbol, Open.
                            </div>

                            <div className="space-y-2">
                              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Visible columns</div>
                              <div className="space-y-2">
                                {resultsColumns.map((key, idx) => (
                                  <div
                                    key={key}
                                    className="flex items-center justify-between rounded-lg border border-outline/10 bg-secondary/10 px-3 py-2 text-sm transition hover:border-outline/16"
                                  >
                                    <div className="flex items-center gap-2">
                                      <button
                                        type="button"
                                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                                        onClick={() => moveResultsColumn(key, 'up')}
                                        disabled={idx === 0}
                                        aria-label={`Move ${RESULTS_COLUMN_LABELS[key]} up`}
                                      >
                                        <ArrowUpIcon className="h-3.5 w-3.5" aria-hidden="true" />
                                      </button>
                                      <button
                                        type="button"
                                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                                        onClick={() => moveResultsColumn(key, 'down')}
                                        disabled={idx === resultsColumns.length - 1}
                                        aria-label={`Move ${RESULTS_COLUMN_LABELS[key]} down`}
                                      >
                                        <ArrowDownIcon className="h-3.5 w-3.5" aria-hidden="true" />
                                      </button>
                                      <span className="text-sm font-medium text-foreground">{RESULTS_COLUMN_LABELS[key]}</span>
                                    </div>
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="sm"
                                      className="h-8 px-2 text-xs"
                                      onClick={() => toggleResultsColumn(key)}
                                    >
                                      Hide
                                    </Button>
                                  </div>
                                ))}
                              </div>
                            </div>

                            {hiddenResultsColumns.length ? (
                              <div className="space-y-2">
                                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Hidden columns</div>
                                <div className="flex flex-wrap gap-2">
                                  {hiddenResultsColumns.map((key) => (
                                    <button
                                      key={key}
                                      type="button"
                                      className="inline-flex items-center gap-2 rounded-full border border-outline/10 bg-card px-3 py-1.5 text-xs font-semibold text-muted-foreground transition hover:border-outline/20 hover:text-foreground"
                                      onClick={() => toggleResultsColumn(key)}
                                    >
                                      <span className="text-[11px]">+</span>
                                      {RESULTS_COLUMN_LABELS[key]}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            ) : null}

                            <div className="space-y-2">
                              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Layouts</div>
                              <div className="flex flex-wrap items-center gap-2">
                                <input
                                  value={layoutName}
                                  onChange={(event) => setLayoutName(event.target.value)}
                                  placeholder="Layout name"
                                  className="h-9 flex-1 rounded-md border border-outline/20 bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                                />
                                <Button
                                  type="button"
                                  size="sm"
                                  className="h-9 rounded-full px-4"
                                  onClick={saveResultsLayout}
                                  disabled={!layoutName.trim()}
                                >
                                  Save
                                </Button>
                              </div>
                              {resultsLayouts.length ? (
                                <div className="space-y-2">
                                  {resultsLayouts.map((layout) => (
                                    <div
                                      key={layout.name}
                                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-outline/10 bg-secondary/10 px-3 py-2"
                                    >
                                      <div className="min-w-0">
                                        <div className="text-sm font-medium text-foreground">{layout.name}</div>
                                        <div className="text-xs text-muted-foreground">
                                          {layout.columns.length} columns
                                        </div>
                                      </div>
                                      <div className="flex items-center gap-2">
                                        <Button
                                          type="button"
                                          variant="outline"
                                          size="sm"
                                          className="h-8 rounded-full px-3 text-xs"
                                          onClick={() => applyResultsLayout(layout)}
                                        >
                                          Apply
                                        </Button>
                                        <Button
                                          type="button"
                                          variant="ghost"
                                          size="sm"
                                          className="h-8 px-2 text-xs text-muted-foreground hover:text-foreground"
                                          onClick={() => removeResultsLayout(layout.name)}
                                        >
                                          Remove
                                        </Button>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="text-xs text-muted-foreground">
                                  Save a layout to quickly switch between column sets.
                                </div>
                              )}
                            </div>
                          </div>

                          <div className="flex items-center justify-between gap-3">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-9 rounded-full px-4"
                              onClick={() => setResultsColumns(DEFAULT_RESULTS_COLUMNS)}
                            >
                              Reset to default
                            </Button>
                            <Button size="sm" className="h-9 rounded-full px-4" onClick={() => setResultsColumnsOpen(false)}>
                              Done
                            </Button>
                          </div>
                        </DialogContent>
                      </Dialog>
                      {isLoading || isError || filteredItems.length === 0 ? (
                        <DataStateWrapper
                          status={isLoading ? 'loading' : isError ? 'error' : 'empty'}
                          context="screener-results"
                          loadingLabel="Loading Screener Results…"
                          title={isError ? 'Data temporarily unavailable' : 'No results'}
                          message={
                            isError
                              ? 'Failed to load screener results.'
                              : activeFilterChips.length
                                ? 'No results for the current filters.'
                                : 'No screener results are available yet.'
                          }
                          lastUpdated={lastUpdatedLabel}
                          filters={activeFilterChips.map((chip) => ({ key: chip.key, label: chip.label, onRemove: chip.onRemove }))}
                          onClearFilters={activeFilterChips.length ? clearFilters : undefined}
                          clearFiltersLabel="Reset filters"
                          tips={
                            activeFilterChips.length
                              ? ['Lower the minimum appearances/styles to expand coverage.', 'Try switching to Movements for daily changes.']
                              : ['Check back after the next pipeline refresh.', 'Try again in a few minutes.']
                          }
                          onRetry={isError ? () => void refetchScreener() : undefined}
                          error={screenerErrorRaw}
                        />
                      ) : resultsView === 'cards' ? (
                        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                          {filteredItems.map((row) => {
                            const rowSymbol = (row.symbol || '').trim().toUpperCase()
                            const preview = rowSymbol ? previews?.[rowSymbol] : previews?.[row.symbol]
                            const isSelected = rowSymbol ? compare.symbols.includes(rowSymbol) : false
                            const focusReturnId = `screener-results-card-${rowSymbol || row.symbol}`
                            const isExpanded = Boolean(expandedRows[rowSymbol])
                            const detailsId = `screener-result-details-card-${rowSymbol || row.symbol}`
                            return (
                              <ClickableCard
                                key={rowSymbol || row.symbol}
                                id={focusReturnId}
                                onActivate={() => {
                                  writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                  if (rowSymbol) handlePrimarySymbolAction(rowSymbol)
                                }}
                                aria-label={`Open details for ${rowSymbol || row.symbol}`}
                                className={cn(
                                  'group flex w-full flex-col rounded-2xl border bg-secondary/15 text-left shadow-sm',
                                  isDense ? 'gap-2 p-3' : 'gap-3 p-4',
                                  isSelected ? 'border-primary/30 bg-secondary/22 shadow-md' : 'border-outline/8',
                                )}
                              >
                                <div className="flex items-start gap-3">
                                  <div className="mt-1 flex w-8 shrink-0 justify-center">
                                    <CompareCheckbox symbol={rowSymbol} tooltipVariant="compact" />
                                  </div>
                                  <div className={cn('min-w-0 flex-1', isDense ? 'space-y-2' : 'space-y-3')}>
                                    <div className="flex flex-wrap items-start justify-between gap-3">
                                      <div className="min-w-0">
                                        <div className="flex flex-wrap items-center gap-2">
                                          <span className={cn('font-semibold', isDense ? 'text-base' : 'text-lg')}>{rowSymbol || row.symbol}</span>
                                          <button
                                            type="button"
                                            onClick={(event) => {
                                              event.stopPropagation()
                                              toggleRowExpanded(rowSymbol)
                                            }}
                                            aria-expanded={isExpanded}
                                            aria-controls={detailsId}
                                            className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                          >
                                            <ChevronDownIcon className={cn('h-4 w-4 transition', isExpanded && 'rotate-180 text-foreground')} aria-hidden />
                                          </button>
                                          <button
                                            type="button"
                                            onClick={(event) => {
                                              event.stopPropagation()
                                              if (rowSymbol) openSymbolSetups(rowSymbol)
                                            }}
                                            className="rounded-full border border-border/60 bg-background/80 px-2 py-0.5 text-[11px] font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                            aria-label={`Open setup hits for ${rowSymbol || row.symbol}`}
                                          >
                                            Setup hits
                                          </button>
                                          {renderChangeBadge(changeHighlights.get(rowSymbol || row.symbol))}
                                        </div>
                                        <div className={cn('mt-0.5 truncate text-muted-foreground', isDense ? 'text-xs' : 'text-sm')}>
                                          {row.company_name || '-'}
                                        </div>
                                        {isResultsColumnVisible('primary') && (row.primary_style || row.primary_source) ? (
                                          <div className={cn('mt-1 text-muted-foreground', isDense ? 'text-[10px]' : 'text-[11px]')}>
                                            Primary {row.primary_style || '-'} / {row.primary_source || '-'}
                                          </div>
                                        ) : null}
                                        {isResultsColumnVisible('ai') ? (
                                          <div className="mt-2">
                                            {preview ? (
                                              <AiPreviewChips preview={preview} />
                                            ) : (
                                              <span className={cn('text-muted-foreground', isDense ? 'text-[10px]' : 'text-xs')}>
                                                No AI memo yet
                                              </span>
                                            )}
                                          </div>
                                        ) : null}
                                      </div>
                                      <div className="flex items-start gap-2">
                                        {isResultsColumnVisible('consensus_score') ? (
                                          <div className="rounded-xl border border-outline/10 bg-card px-3 py-2 text-right">
                                            <div className={cn('font-semibold uppercase tracking-wide text-muted-foreground', isDense ? 'text-[10px]' : 'text-[11px]')}>
                                              Consensus
                                            </div>
                                            <div className={cn('mt-1 font-semibold text-foreground tabular-nums', isDense ? 'text-lg' : 'text-xl')}>
                                              {formatNumberValue(row.consensus_score, 0)}
                                            </div>
                                          </div>
                                        ) : null}
                                        <Tooltip>
                                          <TooltipTrigger asChild>
                                            <button
                                              type="button"
                                              onClick={(event) => {
                                                event.stopPropagation()
                                                writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                                handlePrimarySymbolAction(rowSymbol)
                                              }}
                                              className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                              aria-label={`Open details for ${row.symbol}`}
                                            >
                                              <ExternalLinkIcon className="h-4 w-4" aria-hidden="true" />
                                            </button>
                                          </TooltipTrigger>
                                          <TooltipContent className="px-2 py-1 text-xs">Open ticker details</TooltipContent>
                                        </Tooltip>
                                      </div>
                                    </div>

                                    <div className={cn('grid grid-cols-2 gap-2 sm:grid-cols-3', isDense && 'gap-1.5')}>
                                      {isResultsColumnVisible('rank_best') ? (
                                        <MetricTile dense={isDense} label="Best Rank" value={formatNumberValue(row.rank_best ?? null, 0)} />
                                      ) : null}
                                      {isResultsColumnVisible('appearances') ? (
                                        <MetricTile dense={isDense} label="Appear" value={formatNumberValue(row.appearances ?? null, 1)} />
                                      ) : null}
                                      {isResultsColumnVisible('styles_distinct') ? (
                                        <MetricTile dense={isDense} label="Styles" value={formatNumberValue(row.styles_distinct ?? null, 1)} />
                                      ) : null}
                                      {isResultsColumnVisible('sources_distinct') ? (
                                        <MetricTile dense={isDense} label="Sources" value={formatNumberValue(row.sources_distinct ?? null, 1)} />
                                      ) : null}
                                      {isResultsColumnVisible('min_style_rank_pct') ? (
                                        <MetricTile dense={isDense} label="Best %ile" value={formatPct(row.min_style_rank_pct, 1)} />
                                      ) : null}
                                    </div>
                                    {isExpanded ? (
                                      <div id={detailsId} className="border-t border-outline/10 pt-3">
                                        <ResultRowDetails row={row} />
                                      </div>
                                    ) : null}
                                  </div>
                                </div>
                              </ClickableCard>
                            )
                          })}
                        </div>
                      ) : (
                        <div className="relative overflow-x-auto rounded-2xl border border-border/60">
                          <DataTable className={cn('data-table--sticky', isDense ? 'text-[11px]' : 'text-xs sm:text-sm')}>
                            <thead>
                              <tr className={cn('text-left text-muted-foreground', isDense ? 'text-[10px]' : 'text-xs')}>
                                <th className={cn('sticky top-0 left-0 z-20 w-9 border-b border-border/60 bg-background/90 align-middle backdrop-blur', headerPad, cellPad)}>
                                  <span className="sr-only">Compare</span>
                                </th>
                                <th className={cn('sticky top-0 left-9 z-20 w-9 border-b border-border/60 bg-background/90 align-middle backdrop-blur', headerPad, cellPad)}>
                                  <span className="sr-only">Expand</span>
                                </th>
                                <SortableTh
                                  label="Symbol"
                                  active={sortBy==='symbol'}
                                  order={sortOrder}
                                  onClick={() => handleHeaderSort('symbol')}
                                  tooltip={<TooltipCopyContent tooltipKey="screener.results.symbol" />}
                                  className={cn('sticky top-0 left-[72px] z-20 border-b border-border/60 bg-background/90 backdrop-blur border-r border-border/60', headerPad, cellPad)}
                                />
                                {resultsColumns.map(renderResultsHeader)}
                                <th className={cn('sticky top-0 z-10 w-9 border-b border-border/60 bg-background/90 text-right align-middle backdrop-blur', headerPad, cellPad)}>
                              <span className="sr-only">Open</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredItems.map((row) => {
                            const rowSymbol = (row.symbol || '').trim().toUpperCase()
                            const preview = rowSymbol ? previews?.[rowSymbol] : previews?.[row.symbol]
                            const isSelected = rowSymbol ? compare.symbols.includes(rowSymbol) : false
                            const focusReturnId = `screener-results-row-${rowSymbol || row.symbol}`
                            const isExpanded = Boolean(expandedRows[rowSymbol])
                            const detailsId = `screener-result-details-${rowSymbol || row.symbol}`
                            return (
                              <Fragment key={rowSymbol || row.symbol}>
                                <ClickableTableRow
                                  id={focusReturnId}
                                  onActivate={() => {
                                    writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                    if (rowSymbol) handlePrimarySymbolAction(rowSymbol)
                                  }}
                                  selected={isSelected}
                                  aria-label={`Open details for ${rowSymbol || row.symbol}`}
                                >
                                  <CompareCheckboxCell symbol={rowSymbol} cellClassName={cn('sticky left-0 z-10 w-9 bg-card', rowPad, cellPad)} />
                                  <td
                                    className={cn('sticky left-9 z-10 w-9 bg-card align-middle', rowPad, cellPad)}
                                    onClick={(event) => event.stopPropagation()}
                                    onKeyDown={(event) => event.stopPropagation()}
                                  >
                                    <button
                                      type="button"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        toggleRowExpanded(rowSymbol)
                                      }}
                                      aria-expanded={isExpanded}
                                      aria-controls={detailsId}
                                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                    >
                                      <ChevronDownIcon className={cn('h-4 w-4 transition', isExpanded && 'rotate-180 text-foreground')} aria-hidden />
                                    </button>
                                  </td>
                                  <td className={cn('sticky left-[72px] z-10 bg-card font-semibold align-middle border-r border-outline/10', rowPad, cellPad)}>
                                    <div className="flex items-center gap-2">
                                      <span>{rowSymbol || row.symbol}</span>
                                      <button
                                        type="button"
                                        onClick={(event) => {
                                          event.stopPropagation()
                                          if (rowSymbol) openSymbolSetups(rowSymbol)
                                        }}
                                        className="rounded-full border border-border/60 bg-background/80 px-2 py-0.5 text-[11px] font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                        aria-label={`Open setup hits for ${rowSymbol || row.symbol}`}
                                      >
                                        Setup hits
                                      </button>
                                    </div>
                                    {renderChangeBadge(changeHighlights.get(rowSymbol || row.symbol))}
                                    {(row.primary_style || row.primary_source) ? (
                                      <div className="mt-1 text-[11px] font-medium text-muted-foreground xl:hidden">
                                        Primary {row.primary_style || '-'} / {row.primary_source || '-'}
                                      </div>
                                    ) : null}
                                  {showSparklines && sparklineBySymbol[rowSymbol]?.length ? (
                                      <div className="mt-1">
                                        <MiniSparkline values={sparklineBySymbol[rowSymbol]} />
                                      </div>
                                    ) : null}
                                  </td>
                                  {resultsColumns.map((key) => renderResultsCell(key, row, preview))}
                                  <td className={cn(rowPad, cellPad, 'align-middle text-right')}>
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <button
                                          type="button"
                                          onClick={(event) => {
                                            event.stopPropagation()
                                            writeSessionStorageItem('rankalpha.focusReturnId', focusReturnId)
                                            if (rowSymbol) handlePrimarySymbolAction(rowSymbol)
                                          }}
                                          className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-outline/10 text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                          aria-label={`Open details for ${rowSymbol || row.symbol}`}
                                        >
                                          <ExternalLinkIcon className="h-4 w-4" aria-hidden="true" />
                                        </button>
                                      </TooltipTrigger>
                                      <TooltipContent className="px-2 py-1 text-xs">Open ticker details</TooltipContent>
                                    </Tooltip>
                                  </td>
                                </ClickableTableRow>
                                {isExpanded ? (
                                  <tr id={detailsId} className="border-t bg-secondary/10">
                                    <td colSpan={resultsDetailsColSpan} className="px-3 py-3 sm:px-4">
                                      <ResultRowDetails row={row} />
                                    </td>
                                  </tr>
                                ) : null}
                              </Fragment>
                            )
                          })}
                        </tbody>
                          </DataTable>
                        </div>
                      )}
                    {filteredItems.length > 0 ? (
                      <div className="mt-4 flex flex-wrap items-center justify-end gap-2 text-sm">
                        <button
                          className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                          disabled={page <= 1}
                          onClick={() => setPage((p) => Math.max(1, p - 1))}
                        >
                          Prev
                        </button>
                        <span className="text-xs sm:text-sm">Page {page} / {totalPages}</span>
                        <button
                          className="rounded-md border px-3 py-2 text-xs hover:bg-accent disabled:opacity-50 sm:text-sm"
                          disabled={page >= totalPages}
                          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                        >
                          Next
                        </button>
                      </div>
                    ) : null}
                    </>
                )}
                </CardContent>
              </Card>
            )}


          </section>
        </main>

      </div>
    </div>
  )
}


function sortMovementTriage(items: ScreenerChangeItem[], direction: 'up' | 'down'): ScreenerChangeItem[] {
  const deltaFallback = direction === 'up' ? -Infinity : Infinity
  return [...items].sort((a, b) => {
    const aDelta = Number.isFinite(a.rank_delta) ? Number(a.rank_delta) : deltaFallback
    const bDelta = Number.isFinite(b.rank_delta) ? Number(b.rank_delta) : deltaFallback
    if (aDelta !== bDelta) return direction === 'up' ? bDelta - aDelta : aDelta - bDelta

    const aRank = Number.isFinite(a.current_rank) ? Number(a.current_rank) : Infinity
    const bRank = Number.isFinite(b.current_rank) ? Number(b.current_rank) : Infinity
    if (aRank !== bRank) return aRank - bRank

    const aPrev = Number.isFinite(a.previous_rank) ? Number(a.previous_rank) : Infinity
    const bPrev = Number.isFinite(b.previous_rank) ? Number(b.previous_rank) : Infinity
    if (aPrev !== bPrev) return aPrev - bPrev

    return (a.symbol || '').localeCompare(b.symbol || '')
  })
}

function ChangeColumn({
  title,
  items,
  emptyLabel,
  onPrimaryAction,
  driverLabel,
  hideTitle,
}: {
  title: string
  items: ScreenerChangeItem[]
  emptyLabel: string
  onPrimaryAction: (symbol: string) => void
  driverLabel?: (item: ScreenerChangeItem) => string | null
  hideTitle?: boolean
}) {
  const subset = items
  const [openStyles, setOpenStyles] = useState<Record<string, boolean>>({})

  const groupedByStyle = useMemo(() => {
    const map = new Map<string, ScreenerChangeItem[]>()
    subset.forEach((item) => {
      const style = (item.style || '').trim() || 'Other'
      if (!map.has(style)) map.set(style, [])
      map.get(style)!.push(item)
    })
    const groups = Array.from(map.entries()).map(([style, items]) => ({
      style,
      items: [...items].sort((a, b) => (a.symbol || '').localeCompare(b.symbol || '')),
    }))
    groups.sort((a, b) => b.items.length - a.items.length || a.style.localeCompare(b.style))
    return groups
  }, [subset])

  if (subset.length === 0) {
    return (
      <div>
        {hideTitle ? null : <h3 className="font-semibold text-sm uppercase tracking-wide text-muted-foreground">{title}</h3>}
        <p className="mt-2 text-sm text-muted-foreground">{emptyLabel}</p>
      </div>
    )
  }

  return (
    <div>
      {hideTitle ? null : <h3 className="font-semibold text-sm uppercase tracking-wide text-muted-foreground">{title}</h3>}
      <div className="mt-3 space-y-5">
        {groupedByStyle.map((group) => (
          <div key={group.style}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-2 rounded-md border border-outline/10 bg-card px-3 py-2 text-left transition hover:border-outline/16"
              onClick={() => setOpenStyles((prev) => ({ ...prev, [group.style]: !prev[group.style] }))}
              aria-expanded={Boolean(openStyles[group.style])}
            >
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group.style}</div>
                {!openStyles[group.style] ? (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {group.items.length.toLocaleString()} symbols · {group.items.slice(0, 3).map((it) => it.symbol).join(', ')}
                    {group.items.length > 3 ? '…' : ''}
                  </div>
                ) : (
                  <div className="mt-1 text-xs text-muted-foreground">{group.items.length.toLocaleString()} symbols</div>
                )}
              </div>
              <ChevronDownIcon className={cn('h-4 w-4 text-muted-foreground transition-transform', Boolean(openStyles[group.style]) && 'rotate-180')} />
            </button>
            {openStyles[group.style] ? (
              <ul className="mt-2 space-y-3">
                {group.items.map(item => (
                  <li key={`${item.change_type}-${item.symbol}-${item.source}-${item.style ?? 'none'}`}>
                    <button
                      type="button"
                      onClick={() => onPrimaryAction(item.symbol)}
                      className="group w-full rounded-lg border bg-muted/40 p-3 text-left transition hover:border-primary/40 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                      aria-label={`Open details for ${item.symbol}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <CompareCheckbox symbol={item.symbol} tooltipVariant="compact" />
                          <span className="font-semibold group-hover:text-primary">{item.symbol}</span>
                          {driverLabel ? (
                            (() => {
                              const label = driverLabel(item)
                              if (!label) return null
                              return (
                                <Badge variant="secondary" className="text-[10px] font-semibold">
                                  {label}
                                </Badge>
                              )
                            })()
                          ) : null}
                        </div>
                        <Badge variant={badgeVariantForChange(item.change_type, item.regime_bias, item.position_side)} className="text-xs capitalize">
                          {item.change_type === 'reentered' ? 're-entered' : item.change_type}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{(item.source || '-')}</p>
                      <p className="mt-1 text-xs text-foreground">{describeChange(item)}</p>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}

function MobileChangeSection(props: React.ComponentProps<typeof ChangeColumn> & { title: string }) {
  const [open, setOpen] = useState(false)
  const count = props.items.length

  return (
    <div className="rounded-xl border border-outline/10 bg-card p-3">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <div>
          <div className="text-sm font-semibold">{props.title}</div>
          <div className="text-xs text-muted-foreground">{count.toLocaleString()} symbols</div>
        </div>
        <ChevronDownIcon className={cn('h-4 w-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      {open ? (
        <div className="mt-3">
          <ChangeColumn {...props} hideTitle />
        </div>
      ) : null}
    </div>
  )
}

function TrendBadge({ value, baseline, compact }: { value: number; baseline?: number; compact?: boolean }) {
  const variant: BadgeProps['variant'] = value > 0.0001 ? 'success' : value < -0.0001 ? 'danger' : 'info'
  const delta = baseline !== undefined ? value - baseline : undefined
  return (
    <div className={`flex items-center ${compact ? 'gap-1' : 'gap-2'}`}>
      <Badge variant={variant} className={compact ? 'text-xs font-medium' : 'text-sm font-medium'}>
        {formatPct(value)}
      </Badge>
      {delta !== undefined && !compact && (
        <span className={cn('inline-flex items-center gap-1 text-xs', delta >= 0 ? 'text-status-success' : 'text-status-danger')}>
          {delta >= 0 ? <ArrowUpIcon className="h-3.5 w-3.5" aria-hidden="true" /> : <ArrowDownIcon className="h-3.5 w-3.5" aria-hidden="true" />}
          {formatSigned(delta * 100, 1, '%')} vs 5d
        </span>
      )}
    </div>
  )
}

function renderChangeBadge(items?: ScreenerChangeItem[]) {
  if (!items || items.length === 0) return null
  const entry = items.find(it => it.change_type === 'entered') || items.find(it => it.change_type === 'reentered')
  if (!entry) return null
  const label = entry.change_type === 'entered' ? 'New' : 'Re-entered'
  return (
    <Badge variant={badgeVariantForChange(entry.change_type, entry.regime_bias, entry.position_side)} className="ml-2 text-xs">
      {label}
    </Badge>
  )
}

function badgeVariantForChange(
  type: ScreenerChangeItem['change_type'],
  regimeBias?: 'Bullish' | 'Bearish',
  positionSide?: string,
) {
  const isBearish = regimeBias ? regimeBias === 'Bearish' : (positionSide === 'short')
  if (type === 'entered' || type === 'reentered') return isBearish ? 'danger' : 'success'
  if (type === 'dropped') return isBearish ? 'success' : 'danger'
  return 'info'
}

function formatDate(dateStr?: string) {
  if (!dateStr) return ''
  const formatted = formatEasternDate(dateStr, '')
  return formatted || dateStr
}

function dateDaysAgo(days: number) {
  const d = new Date()
  d.setDate(d.getDate() - Math.max(0, days))
  return formatEasternDate(d)
}

function pluralDays(days?: number | null) {
  if (days === undefined || days === null) return ''
  const value = Math.max(0, Math.round(days))
  return `${value} trading ${value === 1 ? 'day' : 'days'}`
}

function describeChange(item: ScreenerChangeItem) {
  const parts: string[] = []

  if (item.change_type !== 'dropped' && item.current_rank !== undefined && item.current_rank !== null) {
    parts.push(`Rank ${item.current_rank}`)
  }

  if (item.change_type === 'entered') {
    if (item.days_since_last_seen && item.days_since_last_seen > 0) {
      parts.push(`Back after ${pluralDays(item.days_since_last_seen)}`)
    } else {
      parts.push('First appearance')
    }
    if (item.previous_rank !== undefined && item.previous_rank !== null) {
      parts.push(`Prev rank ${item.previous_rank}`)
    }
  } else if (item.change_type === 'reentered') {
    if (item.absent_trading_days && item.absent_trading_days > 0) {
      parts.push(`Back after ${pluralDays(item.absent_trading_days)}`)
    }
    if (item.last_seen_date) {
      parts.push(`Last seen ${formatDate(item.last_seen_date)}`)
    }
  } else {
    if (item.previous_rank !== undefined && item.previous_rank !== null) {
      parts.push(`Was rank ${item.previous_rank}`)
    }
    if (item.absent_trading_days && item.absent_trading_days > 0) {
      parts.push(`Absent ${pluralDays(item.absent_trading_days)}`)
    }
    if (item.last_seen_date) {
      parts.push(`Last seen ${formatDate(item.last_seen_date)}`)
    }
  }

  return parts.filter(Boolean).join(' · ') || '-'
}

function SortableTh({
  label,
  active,
  order,
  onClick,
  align = 'left',
  className,
  tooltip,
}: {
  label: string
  active?: boolean
  order?: 'asc' | 'desc'
  onClick: () => void
  align?: 'left' | 'center' | 'right'
  className?: string
  tooltip?: React.ReactNode
}) {
  const textAlign = align === 'center' ? 'text-center' : align === 'right' ? 'text-right' : 'text-left'
  const justify =
    align === 'center' ? 'mx-auto justify-center' : align === 'right' ? 'ml-auto justify-end' : 'justify-start'
  return (
    <th className={`py-2 pr-4 select-none align-middle ${textAlign} ${className || ''}`}>
      <div className={cn('flex items-center gap-1', justify)}>
        <button
          type="button"
          className={cn(
            'inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-accent',
            active ? 'font-semibold text-foreground' : null,
          )}
          onClick={onClick}
          aria-pressed={active}
          aria-label={`Sort by ${label}`}
        >
          {label}
          {active ? <span className="text-xs text-muted-foreground">{order === 'asc' ? '↑' : '↓'}</span> : null}
        </button>
        {tooltip ? (
          <InfoTooltipButton
            label={label}
            description={tooltip}
            iconSize="h-3.5 w-3.5"
            buttonClassName="text-muted-foreground hover:text-foreground"
            contentClassName="max-w-sm px-3 py-2 text-xs leading-relaxed"
          />
        ) : null}
      </div>
    </th>
  )
}

function AiPreviewChips({ preview }: { preview?: AiPreview }) {
  if (!preview) return null
  const eventsCount = preview.events_count || 0
  const hasThesis = !!preview.has_thesis
  const basePT = preview.base_price_target
  if (!hasThesis && !eventsCount && (basePT === undefined || basePT === null)) return null
  const chips: JSX.Element[] = []
  // if (hasThesis) {
  //   chips.push(<Badge key="thesis" variant="secondary" className="text-xs">Thesis</Badge>)
  // }
  if (typeof basePT === 'number') {
    chips.push(
      <Tooltip key="pt">
        <TooltipTrigger asChild>
          <Badge variant="outline" className="text-xs">
            {UI_TERMS.aiTarget} ${Number(basePT).toFixed(0)}
          </Badge>
        </TooltipTrigger>
        <TooltipContent className="px-3 py-2">
          <TooltipCopyContent tooltipKey="rankings.aiTargetBase" />
        </TooltipContent>
      </Tooltip>,
    )
  }
  // if (eventsCount > 0) {
  //   chips.push(<Badge key="events" variant="outline" className="text-xs">Events {eventsCount}</Badge>)
  // }
  if (chips.length === 0) return null
  const gridColsClass = chips.length > 1 ? 'grid-cols-2' : 'grid-cols-1'
  return (
    <div className={`grid ${gridColsClass} gap-1.5 justify-items-center`}>
      {chips}
    </div>
  )
}

// (format helpers consolidated in `@/lib/format` and `@/lib/nowcast-utils`)
