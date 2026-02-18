'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ActivityIcon, ChevronDownIcon, DropletsIcon, GlobeIcon, ShieldAlertIcon, SparklesIcon, TrendingUpIcon, WavesIcon } from 'lucide-react'

import {
  api,
  BenchmarkSeriesResponse,
  BreadthLatestResponse,
  EmptyResponse,
  FxSeriesResponse,
  FraOisLatestItem,
  HyStressLatestResponse,
  MacroNetLiquidityLatestResponse,
  MacroNetLiquiditySeriesResponse,
  MacroTipsRealYieldSeriesResponse,
  MacroPutCallSeriesResponse,
  MoneyFlowSectorSeriesResponse,
  PriceHistoryList,
  TreasurySeriesResponse,
  VolRegimeResponse,
} from '@/lib/api'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { ChartHeader } from '@/components/charts/chart-header'
import { ChartSkeleton } from '@/components/charts/chart-skeleton'
import { InfoTooltipButton } from '@/components/info_tooltip_button'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Acronym } from '@/components/glossary/acronym'
import { cn } from '@/lib/utils'
import { formatNumberValue, formatPct } from '@/lib/format'
import { buildCycDefAppetiteSeries, formatMillionsToBillionsSigned, formatSigned, isEmptyResponse, lastDelta, stdSample } from '@/lib/nowcast-utils'
import { formatEasternDate } from '@/lib/date'
import { FIVE_MIN_MS } from '@/lib/time'
import { SparklineMini } from '@/features/regime/regime-shared'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { RedactedOverlay } from '@/components/ui/redacted'

function logReturn(a: number, b: number): number | null {
  if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0 || b <= 0) return null
  return Math.log(b / a)
}

function logReturnToPct(logRet?: number | null): number | null {
  if (logRet == null || !Number.isFinite(logRet)) return null
  return (Math.exp(Number(logRet)) - 1) * 100
}

function pctChangeAtLag(values: number[], lag: number): number | null {
  if (values.length <= lag) return null
  const a = values[values.length - 1 - lag]
  const b = values[values.length - 1]
  const r = logReturn(a, b)
  return logReturnToPct(r)
}

function bpChangeAtLag(values: number[], lag: number): number | null {
  if (values.length <= lag) return null
  const a = values[values.length - 1 - lag]
  const b = values[values.length - 1]
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  return (b - a) * 100
}

function realizedVol20AnnPct(values: number[]): number | null {
  if (values.length < 25) return null
  const tail = values.slice(-21)
  const rets: number[] = []
  for (let i = 1; i < tail.length; i++) {
    const r = logReturn(tail[i - 1], tail[i])
    if (r != null) rets.push(r)
  }
  if (rets.length < 10) return null
  const v = stdSample(rets) * Math.sqrt(252) * 100
  return Number.isFinite(v) ? v : null
}

function formatBillions(valueBil?: number | null, digits = 1) {
  if (valueBil == null || !Number.isFinite(valueBil)) return '-'
  return `${Number(valueBil).toFixed(digits)}B`
}

function formatAsOf(value?: string | null) {
  return value ? formatEasternDate(value) : null
}

function pickFra(items: FraOisLatestItem[], start: number, end: number) {
  return items.find((r) => r.start_months === start && r.end_months === end) || null
}

function labelTone(label?: string | null): BadgeProps['variant'] {
  const v = (label || '').toLowerCase()
  if (v.includes('risk_off') || v.includes('crisis') || v.includes('stressed') || v.includes('panic')) return 'danger'
  if (v.includes('risk_on') || v.includes('easy') || v.includes('calm')) return 'success'
  if (v.includes('transition') || v.includes('fragile') || v.includes('warning')) return 'warning'
  return 'secondary'
}

function boolFlag(value?: number | boolean | null) {
  if (value === true) return true
  if (value === false) return false
  if (value == null) return null
  return Number(value) > 0
}

function FlagPill({ label, value }: { label: string; value: number | boolean | null | undefined }) {
  const v = boolFlag(value)
  const tone: BadgeProps['variant'] = v === true ? 'success' : 'secondary'
  return (
    <Badge variant={tone} className="gap-1 px-2 py-0.5 text-[11px]">
      <span className={cn('inline-block h-1.5 w-1.5 rounded-full', v === true ? 'bg-gain' : 'bg-muted-foreground')} />
      {label}
    </Badge>
  )
}

type CrossAssetGroup = 'Duration' | 'Real Rates' | 'Commodity' | 'EM Risk' | 'FX'

type RadarTile = {
  key: string
  group: CrossAssetGroup
  asOf: string | null
  latest: number | null
  latestSuffix?: string
  delta5Pct: number | null
  delta20Pct: number | null
  rv20Pct: number | null
  deltaUnit?: 'pct' | 'bp'
  showRv?: boolean
  spark: Array<{ x: string; y: number }>
  digits: number
}

function ResponsiveSparklineMini(
  props: Omit<Parameters<typeof SparklineMini>[0], 'width'> & { minWidth?: number; expandTitle?: string }
) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState<number>(220)
  const [open, setOpen] = useState(false)
  const [range, setRange] = useState<'1Y' | '6M' | '3M'>('1Y')
  const expandedRef = useRef<HTMLDivElement | null>(null)
  const [expandedWidth, setExpandedWidth] = useState<number>(0)
  const expandTitle = props.expandTitle || props.label || 'Chart'

  useEffect(() => {
    if (!ref.current) return
    const el = ref.current
    const ro = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0]?.contentRect?.width ?? 0)
      if (!w) return
      setWidth(Math.max(props.minWidth ?? 180, w))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [props.minWidth])

  useEffect(() => {
    if (!open) return
    const el = expandedRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0]?.contentRect?.width ?? 0)
      if (!w) return
      setExpandedWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [open])

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          'w-full rounded-md',
          'transition hover:bg-secondary/10',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        )}
        aria-label={`Expand ${expandTitle} chart`}
      >
        <div ref={ref} className="w-full">
          <SparklineMini {...props} width={width} />
        </div>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-4xl">
          <DialogHeader className="flex flex-row items-start justify-between gap-3">
            <div className="min-w-0">
              <DialogTitle className="truncate">{expandTitle}</DialogTitle>
              <div className="mt-1 text-xs text-muted-foreground">Click a sparkline to zoom without leaving the page.</div>
            </div>
            <div className="flex items-center gap-2">
              {(['3M', '6M', '1Y'] as const).map((r) => (
                <Button
                  key={r}
                  type="button"
                  size="sm"
                  variant={range === r ? 'default' : 'outline'}
                  className="h-8 rounded-full px-3 text-xs"
                  onClick={() => setRange(r)}
                >
                  {r}
                </Button>
              ))}
            </div>
          </DialogHeader>

          {(() => {
            const points = props.data ?? []
            const count = range === '1Y' ? 252 : range === '6M' ? 126 : 63
            const slice = points.length > count ? points.slice(-count) : points
            const ys = slice.map((p) => p.y).filter((y) => Number.isFinite(y))
            const last = ys.length ? ys[ys.length - 1] : null
            const prev = ys.length >= 2 ? ys[ys.length - 2] : null
            const mean = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null
            const sd = ys.length >= 10 ? stdSample(ys) : null
            const z = last != null && mean != null && sd && sd > 0 ? (last - mean) / sd : null
            const delta = last != null && prev != null ? last - prev : null
            const fmt = props.format ? props.format : (y: number) => (Number.isFinite(y) ? y.toFixed(2) : '-')

            return (
              <div className="space-y-4">
                <div className="rounded-2xl border border-outline/10 bg-secondary/10 p-4">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Level</div>
                      <div className="mt-1 text-lg font-semibold text-foreground">{last == null ? '-' : fmt(last)}</div>
                    </div>
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Z-score</div>
                      <div className="mt-1 text-lg font-semibold text-foreground">{z == null ? '-' : z.toFixed(2)}</div>
                    </div>
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Most recent change</div>
                      <div className="mt-1 text-lg font-semibold text-foreground">
                        {delta == null ? '-' : formatSigned(delta, 2, '')}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-outline/10 bg-card p-4">
                  <div ref={expandedRef} className="w-full">
                    <SparklineMini
                      {...props}
                      data={slice}
                      width={Math.max(320, expandedWidth)}
                      height={220}
                      label={expandTitle}
                    />
                  </div>
                </div>
              </div>
            )
          })()}
        </DialogContent>
      </Dialog>
    </>
  )
}

export function MacroDashboard() {
  const SECTION_STORAGE_KEY = 'rankalpha.overview.macro_sections.v1'
  const [sectionsOpen, setSectionsOpen] = useState<{ lfc: boolean; vru: boolean; bss: boolean }>({
    lfc: true,
    vru: true,
    bss: true,
  })
  const [sectionsReady, setSectionsReady] = useState(false)

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SECTION_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as Partial<{ lfc: boolean; vru: boolean; bss: boolean }>
      setSectionsOpen((prev) => ({
        ...prev,
        lfc: typeof parsed.lfc === 'boolean' ? parsed.lfc : prev.lfc,
        vru: typeof parsed.vru === 'boolean' ? parsed.vru : prev.vru,
        bss: typeof parsed.bss === 'boolean' ? parsed.bss : prev.bss,
      }))
    } catch {
      // ignore
    } finally {
      setSectionsReady(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(SECTION_STORAGE_KEY, JSON.stringify(sectionsOpen))
    } catch {
      // ignore
    }
  }, [sectionsOpen])

  const lfcEnabled = sectionsReady && sectionsOpen.lfc
  const vruEnabled = sectionsReady && sectionsOpen.vru
  const bssEnabled = sectionsReady && sectionsOpen.bss

  const { data: liquidityLatest, isLoading: liquidityLatestLoading } = useQuery({
    queryKey: ['macro', 'liquidity', 'latest'],
    queryFn: () => api.getMacroLiquidityLatest(),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: rrpSeries } = useQuery({
    queryKey: ['macro', 'liquidity', 'series', 'on_rrp'],
    queryFn: () => api.getMacroLiquiditySeries({ series: 'on_rrp', sort_order: 'desc', limit: 180, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: tgaSeries } = useQuery({
    queryKey: ['macro', 'liquidity', 'series', 'tga'],
    queryFn: () => api.getMacroLiquiditySeries({ series: 'tga', sort_order: 'desc', limit: 180, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: netLiquidityLatest } = useQuery<MacroNetLiquidityLatestResponse>({
    queryKey: ['macro', 'liquidity', 'net-liquidity', 'latest'],
    queryFn: () => api.getMacroNetLiquidityLatest({ lookback_weeks: 520 }),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: netLiquiditySeries } = useQuery<MacroNetLiquiditySeriesResponse>({
    queryKey: ['macro', 'liquidity', 'net-liquidity', 'series'],
    queryFn: () => api.getMacroNetLiquiditySeries({ sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: hyLatest } = useQuery({
    queryKey: ['risk', 'hy-stress', 'latest'],
    queryFn: () => api.getHyStressLatest(),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: hySeries } = useQuery({
    queryKey: ['risk', 'hy-stress', 'series'],
    queryFn: () => api.getHyStressSeries({ sort_order: 'desc', limit: 252, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: fraLatest } = useQuery({
    queryKey: ['rates', 'fra-ois', 'latest'],
    queryFn: () => api.getFraOisLatest({ fra_source: 'SR3' }),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: fraSeries36 } = useQuery({
    queryKey: ['rates', 'fra-ois', 'series', '3x6'],
    queryFn: () => api.getFraOisSeries({ fra_source: 'SR3', start_months: 3, end_months: 6, sort_order: 'desc', limit: 252, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: lfcEnabled,
  })

  const { data: volRegime } = useQuery({
    queryKey: ['macro', 'vol-regime', 'latest'],
    queryFn: () => api.getVolRegimeLatest(),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: putCallEquitySeries } = useQuery<MacroPutCallSeriesResponse>({
    queryKey: ['macro', 'put-call', 'series', 'equity'],
    queryFn: () => api.getMacroPutCallSeries({ series: 'equity', sort_order: 'desc', limit: 252, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: putCallSpxSeries } = useQuery<MacroPutCallSeriesResponse>({
    queryKey: ['macro', 'put-call', 'series', 'spx'],
    queryFn: () => api.getMacroPutCallSeries({ series: 'spx', sort_order: 'desc', limit: 252, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: usdxSeries } = useQuery<BenchmarkSeriesResponse>({
    queryKey: ['benchmarks', 'series', '$USDX'],
    queryFn: () => api.getBenchmarkSeries({ benchmark_name: '$USDX', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: treasurySeries2y } = useQuery<TreasurySeriesResponse>({
    queryKey: ['rates', 'treasury', 'series', '2Y'],
    queryFn: () => api.getTreasurySeries({ tenor: '2Y', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: treasurySeries10y } = useQuery<TreasurySeriesResponse>({
    queryKey: ['rates', 'treasury', 'series', '10Y'],
    queryFn: () => api.getTreasurySeries({ tenor: '10Y', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: fedFundsSeries } = useQuery<TreasurySeriesResponse>({
    queryKey: ['rates', 'treasury', 'series', 'O/N'],
    queryFn: () => api.getTreasurySeries({ tenor: 'O/N', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: tips10ySeries } = useQuery<MacroTipsRealYieldSeriesResponse>({
    queryKey: ['macro', 'real-rates', 'tips10y', 'series'],
    queryFn: () => api.getMacroTipsRealYieldSeries({ sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: tltHistory } = useQuery<PriceHistoryList>({
    queryKey: ['prices', 'history', 'TLT'],
    queryFn: () => api.getPriceHistory({ symbol: 'TLT', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: xauSeries } = useQuery<BenchmarkSeriesResponse>({
    queryKey: ['benchmarks', 'series', 'XAUUSD'],
    queryFn: () => api.getBenchmarkSeries({ benchmark_name: 'XAUUSD', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: wtiSeries } = useQuery<BenchmarkSeriesResponse>({
    queryKey: ['benchmarks', 'series', '@WTI'],
    queryFn: () => api.getBenchmarkSeries({ benchmark_name: '@WTI', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: embHistory } = useQuery<PriceHistoryList>({
    queryKey: ['prices', 'history', 'EMB'],
    queryFn: () => api.getPriceHistory({ symbol: 'EMB', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: usdjpySeries } = useQuery<FxSeriesResponse>({
    queryKey: ['fx', 'series', 'USDJPY'],
    queryFn: () => api.getFxSeries({ pair: 'USDJPY', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: cnyusdSeries } = useQuery<FxSeriesResponse>({
    queryKey: ['fx', 'series', 'CNYUSD'],
    queryFn: () => api.getFxSeries({ pair: 'CNYUSD', sort_order: 'desc', limit: 260, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: vruEnabled,
  })

  const { data: breadthLatest } = useQuery({
    queryKey: ['breadth', 'latest'],
    queryFn: () => api.getBreadthLatest(),
    staleTime: FIVE_MIN_MS,
    enabled: bssEnabled,
  })

  const { data: spxExposureSeries } = useQuery({
    queryKey: ['breadth', 'series', 'SPX', 'target_exposure'],
    queryFn: () => api.getBreadthSeries({ universe: 'SPX', indicator: 'target_exposure', sort_order: 'desc', limit: 252, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: bssEnabled,
  })

  const { data: ndxExposureSeries } = useQuery({
    queryKey: ['breadth', 'series', 'NDX', 'target_exposure'],
    queryFn: () => api.getBreadthSeries({ universe: 'NDX', indicator: 'target_exposure', sort_order: 'desc', limit: 252, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: bssEnabled,
  })

  const { data: nyseAdRatioSeries } = useQuery({
    queryKey: ['breadth', 'series', 'NYSE', 'ad_ratio'],
    queryFn: () => api.getBreadthSeries({ universe: 'NYSE', indicator: 'ad_ratio', sort_order: 'desc', limit: 252, skip: 0 }),
    staleTime: FIVE_MIN_MS,
    enabled: bssEnabled,
  })

  const { data: moneyFlowSectors } = useQuery({
    queryKey: ['money-flow', 'sectors', 'latest'],
    queryFn: () => api.getMoneyFlowSectors(),
    staleTime: FIVE_MIN_MS,
    enabled: bssEnabled,
  })

  const topSector = moneyFlowSectors?.sectors?.[0]?.sector
  const { data: moneyFlowSeries } = useQuery<MoneyFlowSectorSeriesResponse>({
    queryKey: ['money-flow', 'sectors', 'series'],
    queryFn: () => api.getMoneyFlowSectorSeries({ days: 180 }),
    staleTime: FIVE_MIN_MS,
    enabled: bssEnabled,
  })

  const rrpSpark = useMemo(() => {
    const items = [...(rrpSeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: (p.value ?? NaN) / 1_000 }))
      .filter((p) => Number.isFinite(p.y))
  }, [rrpSeries])

  const tgaSpark = useMemo(() => {
    const items = [...(tgaSeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: (p.value ?? NaN) / 1_000 }))
      .filter((p) => Number.isFinite(p.y))
  }, [tgaSeries])

  const netLiq = useMemo(() => {
    if (!netLiquidityLatest || isEmptyResponse(netLiquidityLatest)) return null
    return netLiquidityLatest as Exclude<MacroNetLiquidityLatestResponse, EmptyResponse>
  }, [netLiquidityLatest])

  const netLiqSpark = useMemo(() => {
    const items = [...(netLiquiditySeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.net_liquidity_trn ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [netLiquiditySeries])

  const hyZSpark = useMemo(() => {
    const items = [...(hySeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.hy_stress_z ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [hySeries])

  const hyZMaxAbs = useMemo(() => {
    const ys = hyZSpark.map((p) => p.y)
    if (!ys.length) return 1
    const m = Math.max(...ys.map((y) => Math.abs(y)))
    return m > 0 ? m : 1
  }, [hyZSpark])

  const fraZSpark = useMemo(() => {
    const items = [...(fraSeries36?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.fra_ois_z ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [fraSeries36])

  const fraZMaxAbs = useMemo(() => {
    const ys = fraZSpark.map((p) => p.y)
    if (!ys.length) return 1
    const m = Math.max(...ys.map((y) => Math.abs(y)))
    return m > 0 ? m : 1
  }, [fraZSpark])

  const putCallEquitySpark = useMemo(() => {
    const items = [...(putCallEquitySeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.value ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [putCallEquitySeries])

  const putCallEquityValues = useMemo(() => putCallEquitySpark.map((p) => p.y).filter((v) => Number.isFinite(v)), [putCallEquitySpark])
  const putCallEquityLatest = putCallEquityValues.length ? putCallEquityValues[putCallEquityValues.length - 1] : null
  const putCallEquityDelta5 = useMemo(
    () => lastDelta(putCallEquityValues, Math.min(5, Math.max(1, putCallEquityValues.length - 1))),
    [putCallEquityValues]
  )

  const putCallSpxSpark = useMemo(() => {
    const items = [...(putCallSpxSeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.value ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [putCallSpxSeries])

  const putCallSpxValues = useMemo(() => putCallSpxSpark.map((p) => p.y).filter((v) => Number.isFinite(v)), [putCallSpxSpark])
  const putCallSpxLatest = putCallSpxValues.length ? putCallSpxValues[putCallSpxValues.length - 1] : null
  const putCallSpxDelta5 = useMemo(
    () => lastDelta(putCallSpxValues, Math.min(5, Math.max(1, putCallSpxValues.length - 1))),
    [putCallSpxValues]
  )

  const spxExposureSpark = useMemo(() => {
    const items = [...(spxExposureSeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.value ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [spxExposureSeries])

  const ndxExposureSpark = useMemo(() => {
    const items = [...(ndxExposureSeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.value ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [ndxExposureSeries])

  const nyseAdRatioSpark = useMemo(() => {
    const items = [...(nyseAdRatioSeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.value ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [nyseAdRatioSeries])

  const nyseAdRatioValues = useMemo(() => nyseAdRatioSpark.map((p) => p.y).filter((v) => Number.isFinite(v)), [nyseAdRatioSpark])
  const nyseAdRatioLatest = nyseAdRatioValues.length ? nyseAdRatioValues[nyseAdRatioValues.length - 1] : null
  const nyseAdRatioDelta5 = useMemo(
    () => lastDelta(nyseAdRatioValues, Math.min(5, Math.max(1, nyseAdRatioValues.length - 1))),
    [nyseAdRatioValues]
  )

  const tnxSpark = useMemo(() => {
    const items = [...(treasurySeries10y?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.rate_pct ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [treasurySeries10y])

  const ratesAsOf = tnxSpark.length ? tnxSpark[tnxSpark.length - 1]?.x ?? null : null

  const usdxSpark = useMemo(() => {
    const items = [...(usdxSeries?.items ?? [])].reverse()
    return items
      .map((p) => ({ x: p.as_of_date, y: Number(p.close_px ?? NaN) }))
      .filter((p) => Number.isFinite(p.y))
  }, [usdxSeries])

  const tnxValues = useMemo(() => tnxSpark.map((p) => p.y).filter((v) => Number.isFinite(v)), [tnxSpark])
  const usdxValues = useMemo(() => usdxSpark.map((p) => p.y).filter((v) => Number.isFinite(v)), [usdxSpark])

  const tnxLatest = tnxValues.length ? tnxValues[tnxValues.length - 1] : null
  const usdxLatest = usdxValues.length ? usdxValues[usdxValues.length - 1] : null
  const tnxDelta5 = useMemo(() => lastDelta(tnxValues, Math.min(5, Math.max(1, tnxValues.length - 1))), [tnxValues])
  const usdxDelta5 = useMemo(() => lastDelta(usdxValues, Math.min(5, Math.max(1, usdxValues.length - 1))), [usdxValues])

  const slope2s10sSpark = useMemo(() => {
    const y2 = [...(treasurySeries2y?.items ?? [])].reverse()
    const y10 = [...(treasurySeries10y?.items ?? [])].reverse()
    const map2 = new Map<string, number>()
    y2.forEach((r) => {
      if (r.rate_pct != null && Number.isFinite(r.rate_pct)) map2.set(r.as_of_date, Number(r.rate_pct))
    })
    const pts: Array<{ x: string; y: number }> = []
    y10.forEach((r) => {
      if (r.rate_pct == null || !Number.isFinite(r.rate_pct)) return
      const y2v = map2.get(r.as_of_date)
      if (y2v == null || !Number.isFinite(y2v)) return
      pts.push({ x: r.as_of_date, y: Number(r.rate_pct) - Number(y2v) })
    })
    pts.sort((a, b) => a.x.localeCompare(b.x))
    return pts
  }, [treasurySeries10y, treasurySeries2y])

  const slope2s10sValues = useMemo(() => slope2s10sSpark.map((p) => p.y).filter((v) => Number.isFinite(v)), [slope2s10sSpark])
  const slope2s10sLatest = slope2s10sValues.length ? slope2s10sValues[slope2s10sValues.length - 1] : null
  const slope2s10sDelta20 = useMemo(
    () => lastDelta(slope2s10sValues, Math.min(20, Math.max(1, slope2s10sValues.length - 1))),
    [slope2s10sValues]
  )

  const tips10yValues = useMemo(() => {
    const items = [...(tips10ySeries?.items ?? [])].reverse()
    return items.map((r) => Number(r.value ?? NaN)).filter((v) => Number.isFinite(v))
  }, [tips10ySeries])

  const tips10yLatest = tips10yValues.length ? tips10yValues[tips10yValues.length - 1] : null
  const tips10yDelta20 = useMemo(
    () => lastDelta(tips10yValues, Math.min(20, Math.max(1, tips10yValues.length - 1))),
    [tips10yValues]
  )

  const fedFundsValues = useMemo(() => {
    const items = [...(fedFundsSeries?.items ?? [])].reverse()
    return items.map((r) => Number(r.rate_pct ?? NaN)).filter((v) => Number.isFinite(v))
  }, [fedFundsSeries])

  const fedFundsLatest = fedFundsValues.length ? fedFundsValues[fedFundsValues.length - 1] : null
  const fedFundsDelta20 = useMemo(
    () => lastDelta(fedFundsValues, Math.min(20, Math.max(1, fedFundsValues.length - 1))),
    [fedFundsValues]
  )

  const crossAssetTiles = useMemo<RadarTile[]>(() => {
    const buildPrice = (symbol: string, group: CrossAssetGroup, history?: PriceHistoryList, digits = 2): RadarTile => {
      const items = [...(history?.items ?? [])].reverse()
      const pts = items
        .map((r) => ({ x: r.price_date, y: Number((r.adj_close_px ?? r.close_px) ?? NaN) }))
        .filter((p) => Number.isFinite(p.y) && p.y > 0)
      const values = pts.map((p) => p.y)
      return {
        key: symbol,
        group,
        asOf: pts.length ? pts[pts.length - 1].x : null,
        latest: values.length ? values[values.length - 1] : null,
        delta5Pct: pctChangeAtLag(values, 5),
        delta20Pct: pctChangeAtLag(values, 20),
        rv20Pct: realizedVol20AnnPct(values),
        deltaUnit: 'pct',
        showRv: true,
        spark: pts.slice(-90),
        digits,
      }
    }

    const buildBenchmark = (label: string, group: CrossAssetGroup, series?: BenchmarkSeriesResponse, digits = 2): RadarTile => {
      const items = [...(series?.items ?? [])].reverse()
      const pts = items
        .map((r) => ({ x: r.as_of_date, y: Number(r.close_px ?? NaN) }))
        .filter((p) => Number.isFinite(p.y) && p.y > 0)
      const values = pts.map((p) => p.y)
      return {
        key: label,
        group,
        asOf: pts.length ? pts[pts.length - 1].x : null,
        latest: values.length ? values[values.length - 1] : null,
        delta5Pct: pctChangeAtLag(values, 5),
        delta20Pct: pctChangeAtLag(values, 20),
        rv20Pct: realizedVol20AnnPct(values),
        deltaUnit: 'pct',
        showRv: true,
        spark: pts.slice(-90),
        digits,
      }
    }

    const buildRealRate = (label: string, series?: MacroTipsRealYieldSeriesResponse, digits = 2): RadarTile => {
      const items = [...(series?.items ?? [])].reverse()
      const pts = items.map((r) => ({ x: r.as_of_date, y: Number(r.value ?? NaN) })).filter((p) => Number.isFinite(p.y))
      const values = pts.map((p) => p.y)
      return {
        key: label,
        group: 'Real Rates',
        asOf: pts.length ? pts[pts.length - 1].x : null,
        latest: values.length ? values[values.length - 1] : null,
        latestSuffix: '%',
        delta5Pct: bpChangeAtLag(values, 5),
        delta20Pct: bpChangeAtLag(values, 20),
        rv20Pct: null,
        deltaUnit: 'bp',
        showRv: false,
        spark: pts.slice(-90),
        digits,
      }
    }

    const buildFx = (pair: string, group: CrossAssetGroup, series?: FxSeriesResponse, digits = 4): RadarTile => {
      const items = [...(series?.items ?? [])].reverse()
      const pts = items
        .map((r) => ({ x: r.as_of_date, y: Number(r.mid_px ?? NaN) }))
        .filter((p) => Number.isFinite(p.y) && p.y > 0)
      const values = pts.map((p) => p.y)
      return {
        key: pair,
        group,
        asOf: pts.length ? pts[pts.length - 1].x : null,
        latest: values.length ? values[values.length - 1] : null,
        delta5Pct: pctChangeAtLag(values, 5),
        delta20Pct: pctChangeAtLag(values, 20),
        rv20Pct: realizedVol20AnnPct(values),
        deltaUnit: 'pct',
        showRv: true,
        spark: pts.slice(-90),
        digits,
      }
    }

    const buildFxInverse = (displayPair: string, group: CrossAssetGroup, series?: FxSeriesResponse, digits = 4): RadarTile => {
      const items = [...(series?.items ?? [])].reverse()
      const pts = items
        .map((r) => {
          const v = Number(r.mid_px ?? NaN)
          return { x: r.as_of_date, y: Number.isFinite(v) && v > 0 ? 1 / v : NaN }
        })
        .filter((p) => Number.isFinite(p.y) && p.y > 0)
      const values = pts.map((p) => p.y)
      return {
        key: displayPair,
        group,
        asOf: pts.length ? pts[pts.length - 1].x : null,
        latest: values.length ? values[values.length - 1] : null,
        delta5Pct: pctChangeAtLag(values, 5),
        delta20Pct: pctChangeAtLag(values, 20),
        rv20Pct: realizedVol20AnnPct(values),
        deltaUnit: 'pct',
        showRv: true,
        spark: pts.slice(-90),
        digits,
      }
    }

    return [
      buildPrice('TLT', 'Duration', tltHistory, 2),
      buildRealRate('TIPS10Y', tips10ySeries, 2),
      buildBenchmark('XAUUSD', 'Commodity', xauSeries, 2),
      buildBenchmark('WTI', 'Commodity', wtiSeries, 2),
      buildPrice('EMB', 'EM Risk', embHistory, 2),
      buildFx('USDJPY', 'FX', usdjpySeries, 2),
      buildFxInverse('USDCNY', 'FX', cnyusdSeries, 4),
    ]
  }, [cnyusdSeries, embHistory, tips10ySeries, tltHistory, usdjpySeries, wtiSeries, xauSeries])

  const flowAppetiteSpark = useMemo(() => buildCycDefAppetiteSeries(moneyFlowSeries?.series ?? []), [moneyFlowSeries])

  const flowAppetiteValues = useMemo(() => flowAppetiteSpark.map((p) => p.y).filter((v) => Number.isFinite(v)), [flowAppetiteSpark])
  const flowAppetiteLatest = flowAppetiteValues.length ? flowAppetiteValues[flowAppetiteValues.length - 1] : null
  const flowAppetiteDelta10 = useMemo(
    () => lastDelta(flowAppetiteValues, Math.min(10, Math.max(1, flowAppetiteValues.length - 1))),
    [flowAppetiteValues]
  )

  const fraRows = useMemo(() => {
    if (!fraLatest || isEmptyResponse(fraLatest) || !Array.isArray(fraLatest)) return null
    const rows = fraLatest as FraOisLatestItem[]
    return {
      r36: pickFra(rows, 3, 6),
      r69: pickFra(rows, 6, 9),
      r912: pickFra(rows, 9, 12),
      all: rows,
    }
  }, [fraLatest])

  const fundingAsOf = useMemo(() => {
    return fraRows?.r36?.as_of_date ?? fraRows?.r69?.as_of_date ?? fraRows?.r912?.as_of_date ?? null
  }, [fraRows])

  const hy = useMemo(() => {
    if (!hyLatest || isEmptyResponse(hyLatest)) return null
    return hyLatest as Exclude<HyStressLatestResponse, EmptyResponse>
  }, [hyLatest])

  const vr = useMemo(() => {
    if (!volRegime || isEmptyResponse(volRegime)) return null
    return volRegime as Exclude<VolRegimeResponse, EmptyResponse>
  }, [volRegime])

  const bl = breadthLatest as BreadthLatestResponse | undefined

  return (
    <section className="space-y-4" aria-label="Macro dashboard">
      <h2 className="sr-only">Macro dashboard</h2>

      <details
        open={sectionsOpen.lfc}
        onToggle={(e) => {
          const nextOpen = e.currentTarget.open
          setSectionsOpen((prev) => ({ ...prev, lfc: nextOpen }))
        }}
        className="group rounded-2xl border border-outline/10 bg-card shadow-sm"
      >
        <summary
          className={cn(
            'flex list-none items-center justify-between gap-3 px-4 py-3',
            'cursor-pointer select-none',
            'transition hover:bg-secondary/10',
            'marker:hidden [&::-webkit-details-marker]:hidden',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          )}
        >
          <div>
            <div className="text-sm font-semibold">Liquidity / Funding / Credit</div>
            <div className="text-xs text-muted-foreground">Core stress gauges that feed the risk nowcast.</div>
          </div>
          <ChevronDownIcon className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        {lfcEnabled ? (
          <div className="px-4 pb-4">
            <div className="grid gap-4 lg:grid-cols-3">
              <LiquidityCard
                loading={liquidityLatestLoading && !liquidityLatest}
                asOf={liquidityLatest?.as_of_date}
                regime={liquidityLatest?.regime ?? null}
                rrpValueBil={liquidityLatest?.rrp_value_bil ?? null}
                tgaValueBil={liquidityLatest?.tga_value_bil ?? null}
                rrpDeltaMn={liquidityLatest?.rrp_change_mn ?? null}
                tgaDeltaMn={liquidityLatest?.tga_change_mn ?? null}
                netLiquidityTrn={netLiq?.net_liquidity_trn ?? null}
                netLiquidityDelta4wTrn={netLiq?.delta_4w_trn ?? null}
                netLiquidityDelta13wTrn={netLiq?.delta_13w_trn ?? null}
                rrpSpark={rrpSpark}
                tgaSpark={tgaSpark}
                netLiquiditySpark={netLiqSpark}
              />

              <FundingCard
                asOf={fundingAsOf}
                r36={fraRows?.r36 ?? null}
                r69={fraRows?.r69 ?? null}
                r912={fraRows?.r912 ?? null}
                spark={fraZSpark}
                domainMaxAbs={fraZMaxAbs}
              />

              <CreditCard asOf={hy?.as_of_date ?? null} hy={hy} spark={hyZSpark} domainMaxAbs={hyZMaxAbs} />
            </div>
          </div>
        ) : null}
      </details>

      <details
        open={sectionsOpen.vru}
        onToggle={(e) => {
          const nextOpen = e.currentTarget.open
          setSectionsOpen((prev) => ({ ...prev, vru: nextOpen }))
        }}
        className="group rounded-2xl border border-outline/10 bg-card shadow-sm"
      >
        <summary
          className={cn(
            'flex list-none items-center justify-between gap-3 px-4 py-3',
            'cursor-pointer select-none',
            'transition hover:bg-secondary/10',
            'marker:hidden [&::-webkit-details-marker]:hidden',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          )}
        >
          <div>
            <div className="text-sm font-semibold">Vol / Rates / USD</div>
            <div className="text-xs text-muted-foreground">Volatility + cost-of-capital + dollar strength.</div>
          </div>
          <ChevronDownIcon className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        {vruEnabled ? (
          <div className="px-4 pb-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <VolCard
                asOf={vr?.as_of_date ?? null}
                vr={vr}
                putCallEquityLatest={putCallEquityLatest}
                putCallEquityDelta5={putCallEquityDelta5}
                putCallEquitySpark={putCallEquitySpark}
                putCallSpxLatest={putCallSpxLatest}
                putCallSpxDelta5={putCallSpxDelta5}
                putCallSpxSpark={putCallSpxSpark}
              />

              <RatesUsdCard
                asOf={ratesAsOf}
                tnxLatest={tnxLatest}
                tnxDelta5={tnxDelta5}
                usdxLatest={usdxLatest}
                usdxDelta5={usdxDelta5}
                slope2s10sLatest={slope2s10sLatest}
                slope2s10sDelta20={slope2s10sDelta20}
                tips10yLatest={tips10yLatest}
                tips10yDelta20={tips10yDelta20}
                fedFundsLatest={fedFundsLatest}
                fedFundsDelta20={fedFundsDelta20}
                tnxSpark={tnxSpark}
                usdxSpark={usdxSpark}
                slopeSpark={slope2s10sSpark}
              />

              <div className="lg:col-span-2">
                <CrossAssetCard tiles={crossAssetTiles} />
              </div>
            </div>
          </div>
        ) : null}
      </details>

      <details
        open={sectionsOpen.bss}
        onToggle={(e) => {
          const nextOpen = e.currentTarget.open
          setSectionsOpen((prev) => ({ ...prev, bss: nextOpen }))
        }}
        className="group rounded-2xl border border-outline/10 bg-card shadow-sm"
      >
        <summary
          className={cn(
            'flex list-none items-center justify-between gap-3 px-4 py-3',
            'cursor-pointer select-none',
            'transition hover:bg-secondary/10',
            'marker:hidden [&::-webkit-details-marker]:hidden',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          )}
        >
          <div>
            <div className="text-sm font-semibold">Breadth / Flows / Structure</div>
            <div className="text-xs text-muted-foreground">Participation, sector leadership, and positioning proxies.</div>
          </div>
          <ChevronDownIcon className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        {bssEnabled ? (
          <div className="px-4 pb-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <BreadthCard
                asOf={bl?.as_of_date ?? null}
                breadthLatest={bl}
                spxSpark={spxExposureSpark}
                ndxSpark={ndxExposureSpark}
                nyseAdRatioLatest={nyseAdRatioLatest}
                nyseAdRatioDelta5={nyseAdRatioDelta5}
                nyseAdRatioSpark={nyseAdRatioSpark}
              />

              <MoneyFlowCard
                asOf={moneyFlowSectors?.as_of_date ?? null}
                sectors={moneyFlowSectors?.sectors ?? []}
                topSector={topSector ?? null}
                appetiteLatest={flowAppetiteLatest}
                appetiteDelta10={flowAppetiteDelta10}
                spark={flowAppetiteSpark}
              />
            </div>
          </div>
        ) : null}
      </details>
    </section>
  )
}

function LiquidityCard(props: {
  loading: boolean
  asOf?: string | null
  regime: string | null
  rrpValueBil: number | null
  tgaValueBil: number | null
  rrpDeltaMn: number | null
  tgaDeltaMn: number | null
  netLiquidityTrn: number | null
  netLiquidityDelta4wTrn: number | null
  netLiquidityDelta13wTrn: number | null
  rrpSpark: { x: string; y: number }[]
  tgaSpark: { x: string; y: number }[]
  netLiquiditySpark: { x: string; y: number }[]
}) {
  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <DropletsIcon className="h-4 w-4" />
              <span>Liquidity</span>
              <span className="text-xs text-muted-foreground">
                (
                <Acronym term="ON RRP" className="text-xs text-muted-foreground" /> /{' '}
                <Acronym term="TGA" className="text-xs text-muted-foreground" />)
              </span>
            </span>
          )}
          description="System liquidity and policy plumbing inputs that steer risk appetite."
          tooltipKey="macro.liquidity"
          tooltipLabel="Liquidity"
          updatedAt={formatAsOf(props.asOf)}
          methodologyHref="/about/nowcast"
          stats={props.regime ? (
            <Badge variant={labelTone(props.regime)} className="px-2 py-0.5 text-xs">
              {props.regime}
            </Badge>
          ) : (
            <Badge variant="secondary" className="px-2 py-0.5 text-xs">
              -
            </Badge>
          )}
        />
      </CardHeader>
      <CardContent className="space-y-3">
        {props.loading ? (
          <ChartSkeleton className="h-32" />
        ) : (
          <>
            <div className="space-y-3">
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">ON RRP</div>
                    <div className="mt-1 text-lg font-semibold">{formatBillions(props.rrpValueBil)}</div>
                    <div className="text-xs text-muted-foreground">Δ {formatMillionsToBillionsSigned(props.rrpDeltaMn)}</div>
                  </div>
                  <div className="w-full min-w-0 sm:w-[42%] sm:min-w-[140px] sm:max-w-[220px]">
                    <ResponsiveSparklineMini data={props.rrpSpark} height={58} color="#0ea5e9" label="RRP" minWidth={0} />
                  </div>
                </div>
              </div>
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">TGA</div>
                    <div className="mt-1 text-lg font-semibold">{formatBillions(props.tgaValueBil)}</div>
                    <div className="text-xs text-muted-foreground">Δ {formatMillionsToBillionsSigned(props.tgaDeltaMn)}</div>
                  </div>
                  <div className="w-full min-w-0 sm:w-[42%] sm:min-w-[140px] sm:max-w-[220px]">
                    <ResponsiveSparklineMini data={props.tgaSpark} height={58} color="#f59e0b" label="TGA" minWidth={0} />
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Net Liquidity</div>
                  <div className="mt-1 text-lg font-semibold">
                    {props.netLiquidityTrn == null ? '-' : `${formatNumberValue(props.netLiquidityTrn, 2)}T`}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Δ4w {formatSigned(props.netLiquidityDelta4wTrn, 2, 'T')} • Δ13w {formatSigned(props.netLiquidityDelta13wTrn, 2, 'T')}
                  </div>
                </div>
                <div className="w-full min-w-0 sm:w-[42%] sm:min-w-[140px] sm:max-w-[220px]">
                  <ResponsiveSparklineMini data={props.netLiquiditySpark} height={58} color="#22c55e" label="NetLiq" minWidth={0} />
                </div>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function FundingCard(props: {
  asOf?: string | null
  r36: FraOisLatestItem | null
  r69: FraOisLatestItem | null
  r912: FraOisLatestItem | null
  spark: { x: string; y: number }[]
  domainMaxAbs: number
}) {
  const main = props.r36
  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <ActivityIcon className="h-4 w-4" />
              <span>Funding Stress</span>
              <span className="text-xs text-muted-foreground">
                (<Acronym term="FRA–OIS" className="text-xs text-muted-foreground" />)
              </span>
            </span>
          )}
          description="Funding market tightness proxy (higher = tighter conditions)."
          tooltipKey="macro.fundingStress"
          tooltipLabel="Funding stress"
          updatedAt={formatAsOf(props.asOf ?? main?.as_of_date ?? null)}
          methodologyHref="/about/nowcast"
        />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-col gap-3 rounded-xl border border-outline/10 bg-secondary/15 p-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">3x6 (SR3)</div>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-lg font-semibold">{main?.spread_bp != null ? `${formatNumberValue(main.spread_bp, 1)} bp` : '-'}</span>
              <Badge variant={labelTone(main?.regime)}>{main?.regime ?? '-'}</Badge>
            </div>
            <div className="text-xs text-muted-foreground">z {formatNumberValue(main?.fra_ois_z, 2)}</div>
          </div>
          <div className="w-full min-w-0 sm:w-[40%] sm:min-w-[140px] sm:max-w-[200px]">
            <ResponsiveSparklineMini
              data={props.spark}
              height={58}
              domainY={[-props.domainMaxAbs, props.domainMaxAbs]}
              color="#a78bfa"
              label="z"
              minWidth={0}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
          <TenorPill label="6x9" row={props.r69} />
          <TenorPill label="9x12" row={props.r912} />
          <TenorPill label="3x6" row={props.r36} />
        </div>
      </CardContent>
    </Card>
  )
}

function TenorPill({ label, row }: { label: string; row: FraOisLatestItem | null }) {
  return (
    <div className="min-w-0 rounded-xl border border-outline/10 bg-card p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
        <Badge variant={labelTone(row?.regime)} className="shrink-0 px-2 py-0.5 text-[10px]">
          {row?.regime ?? '-'}
        </Badge>
      </div>
      <div className="mt-1 truncate font-semibold">{row?.spread_bp != null ? `${formatNumberValue(row.spread_bp, 1)} bp` : '-'}</div>
    </div>
  )
}

function CreditCard(props: { asOf?: string | null; hy: Exclude<HyStressLatestResponse, EmptyResponse> | null; spark: { x: string; y: number }[]; domainMaxAbs: number }) {
  const hy = props.hy
  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <ShieldAlertIcon className="h-4 w-4" />
              <span>Credit Stress</span>
              <span className="text-xs text-muted-foreground">
                (<Acronym term="HY OAS" className="text-xs text-muted-foreground" />)
              </span>
            </span>
          )}
          description="High-yield spread stress proxy (wider = more risk aversion)."
          tooltipKey="macro.creditStress"
          tooltipLabel="Credit stress"
          updatedAt={formatAsOf(props.asOf ?? hy?.as_of_date ?? null)}
          methodologyHref="/about/nowcast"
        />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-col gap-3 rounded-xl border border-outline/10 bg-secondary/15 p-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">z (750d)</div>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-lg font-semibold">{formatNumberValue(hy?.hy_stress_z, 2)}</span>
              <Badge variant={labelTone(hy?.label)}>{hy?.label ?? '-'}</Badge>
            </div>
            <div className="text-xs text-muted-foreground">MA10 {formatNumberValue(hy?.hy_stress_ma, 2)}</div>
          </div>
          <div className="w-full min-w-0 sm:w-[40%] sm:min-w-[140px] sm:max-w-[200px]">
            <ResponsiveSparklineMini
              data={props.spark}
              height={58}
              domainY={[-props.domainMaxAbs, props.domainMaxAbs]}
              color="#ef4444"
              label="z"
              minWidth={0}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function VolCard(props: {
  asOf?: string | null
  vr: Exclude<VolRegimeResponse, EmptyResponse> | null
  putCallEquityLatest: number | null
  putCallEquityDelta5: number | null
  putCallEquitySpark: { x: string; y: number }[]
  putCallSpxLatest: number | null
  putCallSpxDelta5: number | null
  putCallSpxSpark: { x: string; y: number }[]
}) {
  const vr = props.vr
  const contango = vr?.is_contango_full ?? vr?.is_contango
  const backward = vr?.is_backwardation_front ?? vr?.is_backwardation_short
  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <WavesIcon className="h-4 w-4" />
              <span>Vol Regime</span>
              <span className="text-xs text-muted-foreground">
                (
                <Acronym term="VIX" className="text-xs text-muted-foreground" /> +{' '}
                <Acronym term="VRP" className="text-xs text-muted-foreground" />)
              </span>
            </span>
          )}
          description="Volatility and VRP context for risk budget pressure."
          tooltipKey="macro.vol"
          tooltipLabel="Vol regime"
          updatedAt={formatAsOf(props.asOf ?? vr?.as_of_date ?? null)}
          methodologyHref="/about/nowcast"
        />
      </CardHeader>
      <CardContent className="space-y-3">
        {!vr ? (
          <p className="text-sm text-muted-foreground">No vol regime data available.</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">VIX (1M)</div>
                <div className="mt-1 text-2xl font-semibold">{formatNumberValue(vr.vix_1m, 1)}</div>
                <div className="text-xs text-muted-foreground">Curve slope {formatNumberValue(vr.curve_slope, 2)}</div>
              </div>
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">VRP</div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="text-2xl font-semibold">{formatNumberValue(vr.vrp_30d, 4)}</span>
                  <Badge variant={labelTone(vr.vrp_regime)}>{vr.vrp_regime ?? '-'}</Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  State: {vr.vrp_state ?? '-'} · Vol: {vr.vol_state ?? '-'}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <FlagPill label="Contango" value={contango ?? null} />
              <FlagPill label="Backwardation" value={backward ?? null} />
              <FlagPill label="Risk flag" value={vr.risk_flag ?? null} />
              {vr.regime ? (
                <Badge variant="outline" className="rounded-full">
                  {vr.regime}
                </Badge>
              ) : null}
            </div>

            <div className="grid gap-3">
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Put/Call (Equity, context)</div>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-xl font-semibold">{props.putCallEquityLatest == null ? '-' : formatNumberValue(props.putCallEquityLatest, 2)}</span>
                  <span className="text-xs text-muted-foreground">Δ5d {formatSigned(props.putCallEquityDelta5, 2)}</span>
                </div>
                <div className="mt-2">
                  <ResponsiveSparklineMini data={props.putCallEquitySpark} height={52} color="#94a3b8" label="P/C" neutralBand={[0.8, 1.2]} />
                </div>
              </div>
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Put/Call (SPX, context)</div>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-xl font-semibold">{props.putCallSpxLatest == null ? '-' : formatNumberValue(props.putCallSpxLatest, 2)}</span>
                  <span className="text-xs text-muted-foreground">Δ5d {formatSigned(props.putCallSpxDelta5, 2)}</span>
                </div>
                <div className="mt-2">
                  <ResponsiveSparklineMini data={props.putCallSpxSpark} height={52} color="#a78bfa" label="SPX" neutralBand={[1.2, 1.8]} />
                </div>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function RatesUsdCard(props: {
  asOf?: string | null
  tnxLatest: number | null
  tnxDelta5: number | null
  usdxLatest: number | null
  usdxDelta5: number | null
  slope2s10sLatest: number | null
  slope2s10sDelta20: number | null
  tips10yLatest: number | null
  tips10yDelta20: number | null
  fedFundsLatest: number | null
  fedFundsDelta20: number | null
  tnxSpark: { x: string; y: number }[]
  usdxSpark: { x: string; y: number }[]
  slopeSpark: { x: string; y: number }[]
}) {
  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <TrendingUpIcon className="h-4 w-4" />
              <span>Rates & USD</span>
              <InfoTooltipButton
                label="Rates & USD"
                iconSize="h-3.5 w-3.5"
                description="Cost-of-capital and tightening channels: 10Y Treasury yield, Fed Funds (O/N), USD strength ($USDX), curve slope (2s10s), and 10Y TIPS real yield."
              />
            </span>
          )}
          description="Levels, deltas, and sparklines for rates and FX tightening proxies."
          updatedAt={formatAsOf(props.asOf)}
          methodologyHref="/about/nowcast"
        />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">10Y (Treasury)</div>
              <div className="mt-1 text-lg font-semibold">{props.tnxLatest == null ? '-' : formatNumberValue(props.tnxLatest, 2)}</div>
              <div className="text-xs text-muted-foreground">Δ {formatSigned(props.tnxDelta5, 2)}</div>
            </div>
            <div className="w-full min-w-0 sm:w-[42%] sm:min-w-[140px] sm:max-w-[220px]">
              <ResponsiveSparklineMini data={props.tnxSpark} height={58} color="#f97316" label="10Y" minWidth={0} />
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">USD ($USDX)</div>
              <div className="mt-1 text-lg font-semibold">{props.usdxLatest == null ? '-' : formatNumberValue(props.usdxLatest, 1)}</div>
              <div className="text-xs text-muted-foreground">Δ {formatSigned(props.usdxDelta5, 2)}</div>
            </div>
            <div className="w-full min-w-0 sm:w-[42%] sm:min-w-[140px] sm:max-w-[220px]">
              <ResponsiveSparklineMini data={props.usdxSpark} height={58} color="#0ea5e9" label="USDX" minWidth={0} />
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Curve + Real Rates</div>
              <div className="mt-1 flex items-center gap-2">
                <span className="text-lg font-semibold">
                  2s10s {props.slope2s10sLatest == null ? '-' : `${formatNumberValue(props.slope2s10sLatest * 100, 0)}bp`}
                </span>
                <span className="text-xs text-muted-foreground">Δ20d {formatSigned(props.slope2s10sDelta20 == null ? null : props.slope2s10sDelta20 * 100, 0, 'bp')}</span>
              </div>
              <div className="text-xs text-muted-foreground">
                TIPS 10Y {props.tips10yLatest == null ? '-' : `${formatNumberValue(props.tips10yLatest, 2)}%`} • Δ20d{' '}
                {props.tips10yDelta20 == null ? '-' : formatSigned(props.tips10yDelta20 * 100, 0, 'bp')}
              </div>
              <div className="text-xs text-muted-foreground">
                Fed Funds (O/N) {props.fedFundsLatest == null ? '-' : `${formatNumberValue(props.fedFundsLatest, 2)}%`} • Δ20d{' '}
                {props.fedFundsDelta20 == null ? '-' : formatSigned(props.fedFundsDelta20 * 100, 0, 'bp')}
              </div>
            </div>
            <div className="w-full min-w-0 sm:w-[42%] sm:min-w-[140px] sm:max-w-[220px]">
              <ResponsiveSparklineMini data={props.slopeSpark} height={58} color="#a78bfa" label="2s10s" minWidth={0} />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function BreadthCard(props: {
  asOf?: string | null
  breadthLatest?: BreadthLatestResponse
  spxSpark: { x: string; y: number }[]
  ndxSpark: { x: string; y: number }[]
  nyseAdRatioLatest: number | null
  nyseAdRatioDelta5: number | null
  nyseAdRatioSpark: { x: string; y: number }[]
}) {
  const b = props.breadthLatest
  const spx = b?.spx ?? {}
  const ndx = b?.ndx ?? {}
  const nyse = b?.nyse ?? {}

  const spxLabel = (spx as any).regime_label as string | undefined
  const ndxLabel = (ndx as any).regime_label as string | undefined
  const hinden = (nyse as any).hindenburg_confirmed
  const trin = (nyse as any).trin_stress
  const lows = (nyse as any).persistent_new_lows
  const zwbt = (nyse as any).zweig_breadth_thrust
  const zwbtOn = zwbt == null ? null : Number(zwbt) >= 0.615

  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <SparklesIcon className="h-4 w-4" />
              <span>Market Breadth</span>
              <InfoTooltipButton
                label="Breadth"
                iconSize="h-3.5 w-3.5"
                description="Derived breadth signals for SPX/NDX/NYSE, including a target-exposure proxy from thrust vs fragility scoring."
              />
            </span>
          )}
          description="Participation and thrust signals that shape regime context."
          updatedAt={formatAsOf(props.asOf ?? b?.as_of_date ?? null)}
          methodologyHref="/about/regime"
        />
      </CardHeader>
      <CardContent className="space-y-3">
        {!b ? (
          <p className="text-sm text-muted-foreground">No breadth data available.</p>
        ) : (
          <>
            <div className="space-y-3">
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">SPX target exposure</div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="text-lg font-semibold">{formatPct((spx as any).target_exposure, 0)}</span>
                      <Badge variant={labelTone(spxLabel)}>{spxLabel ?? '-'}</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">Net score {formatNumberValue((spx as any).net_score, 2)}</div>
                  </div>
                  <div className="w-full min-w-0 sm:w-[38%] sm:min-w-[120px] sm:max-w-[180px]">
                    <ResponsiveSparklineMini data={props.spxSpark} height={58} domainY={[0, 1]} color="#10b981" label="SPX" minWidth={0} />
                  </div>
                </div>
              </div>
              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">NDX target exposure</div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="text-lg font-semibold">{formatPct((ndx as any).target_exposure, 0)}</span>
                      <Badge variant={labelTone(ndxLabel)}>{ndxLabel ?? '-'}</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">Net score {formatNumberValue((ndx as any).net_score, 2)}</div>
                  </div>
                  <div className="w-full min-w-0 sm:w-[38%] sm:min-w-[120px] sm:max-w-[180px]">
                    <ResponsiveSparklineMini data={props.ndxSpark} height={58} domainY={[0, 1]} color="#22c55e" label="NDX" minWidth={0} />
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      NYSE <Acronym term="A/D" className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground" /> ratio (context)
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="text-lg font-semibold">{props.nyseAdRatioLatest == null ? '-' : formatNumberValue(props.nyseAdRatioLatest, 2)}</span>
                      <span className="text-xs text-muted-foreground">Δ5d {formatSigned(props.nyseAdRatioDelta5, 2)}</span>
                    </div>
                  </div>
                  <div className="w-full min-w-0 sm:w-[38%] sm:min-w-[120px] sm:max-w-[180px]">
                    <ResponsiveSparklineMini
                      data={props.nyseAdRatioSpark}
                      height={58}
                      color="#f59e0b"
                      label="ADVR"
                      neutralBand={[0.9, 1.1]}
                      minWidth={0}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <FlagPill label="Hindenburg" value={hinden ?? null} />
              <FlagPill label="TRIN stress" value={trin ?? null} />
              <FlagPill label="Persistent lows" value={lows ?? null} />
              <FlagPill label="Zweig thrust" value={zwbtOn} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function MoneyFlowCard(props: {
  asOf: string | null
  sectors: Array<{ sector: string; sector_etf?: string | null; avg_score: number | null }>
  topSector: string | null
  appetiteLatest: number | null
  appetiteDelta10: number | null
  spark: { x: string; y: number }[]
}) {
  const top = props.sectors.slice(0, 5)
  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <TrendingUpIcon className="h-4 w-4" />
              <span>Money Flow (Risk Appetite)</span>
              <InfoTooltipButton
                label="Money flow"
                iconSize="h-3.5 w-3.5"
                description="Risk appetite proxy from sector money-flow scores: cyclical minus defensive. Top sectors are shown for context."
              />
            </span>
          )}
          description="Cyclical minus defensive leadership as a positioning proxy."
          updatedAt={formatAsOf(props.asOf)}
          methodologyHref="/about/regime"
        />
      </CardHeader>
      <CardContent className="space-y-3">
        {!props.sectors.length ? (
          <p className="text-sm text-muted-foreground">No money flow data available.</p>
        ) : (
          <>
            <div className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Cyclical − Defensive</div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-lg font-semibold">{props.appetiteLatest == null ? '-' : formatSigned(props.appetiteLatest, 1)}</span>
                    <span className="text-xs text-muted-foreground">Δ10d {formatSigned(props.appetiteDelta10, 1)}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {props.topSector ? `Top: ${props.topSector}` : 'Top: -'} · Avg score {props.sectors[0]?.avg_score != null ? formatNumberValue(props.sectors[0].avg_score, 1) : '-'}
                  </div>
                </div>
                <div className="w-full min-w-0 sm:w-[40%] sm:min-w-[140px] sm:max-w-[220px]">
                  <ResponsiveSparklineMini
                    data={props.spark}
                    height={58}
                    color="#0ea5e9"
                    label="Cyc−Def"
                    neutralBand={[-2, 2]}
                    minWidth={0}
                  />
                </div>
              </div>
            </div>

            <div className="space-y-1.5 text-sm">
              {top.map((s) => (
                <div key={s.sector} className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-xs font-medium">{s.sector}</span>
                    {s.sector_etf ? (
                      <span className="rounded-full border border-outline/10 bg-card px-2 py-0.5 text-[11px] text-muted-foreground">
                        {s.sector_etf}
                      </span>
                    ) : null}
                  </div>
                  <span className="text-xs font-semibold tabular-nums">{s.avg_score != null ? formatNumberValue(s.avg_score, 1) : '-'}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function CrossAssetCard(props: { tiles: RadarTile[] }) {
  const showRawData = SHOW_RAW_DATA
  const asOf = useMemo(() => {
    const dates = props.tiles.map((t) => t.asOf).filter((d): d is string => !!d)
    return dates.length ? dates.sort().at(-1) || null : null
  }, [props.tiles])

  const hasAny = props.tiles.some((t) => t.latest != null && Number.isFinite(t.latest))

  const groupTone = (_g: CrossAssetGroup): BadgeProps['variant'] => 'info'

  return (
    <Card className="border-outline/8">
      <CardHeader className="pb-2">
        <ChartHeader
          title={(
            <span className="inline-flex items-center gap-2">
              <GlobeIcon className="h-4 w-4" />
              <span>Cross‑Asset Radar (Context)</span>
              <InfoTooltipButton
                label="Cross-asset radar"
                iconSize="h-3.5 w-3.5"
                description="Peripheral world-view across duration (TLT), real rates (TIPS10Y), commodities (XAUUSD/WTI), EM risk (EMB), and FX (USDJPY/USDCNY). Context-only; not part of the Risk Nowcast weight."
              />
            </span>
          )}
          description="Peripheral cross-asset context for divergences and stress."
          updatedAt={formatAsOf(asOf)}
          methodologyHref="/about/nowcast"
        />
      </CardHeader>
      <CardContent className="space-y-3">
        {!hasAny ? (
          <p className="text-sm text-muted-foreground">No cross-asset data available.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {props.tiles.map((t) => (
              <div key={t.key} className="relative rounded-xl border border-outline/10 bg-secondary/15 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t.key}</div>
                      <Badge variant={groupTone(t.group)} className="px-2 py-0.5 text-[10px]">
                        {t.group}
                      </Badge>
                    </div>
                    <div className={cn('mt-1 text-lg font-semibold tabular-nums', !showRawData && 'blur-sm select-none text-muted-foreground')}>
                      {!showRawData ? '****' : t.latest == null ? '-' : `${formatNumberValue(t.latest, t.digits)}${t.latestSuffix ?? ''}`}
                    </div>
                    <div className={cn('text-xs text-muted-foreground', !showRawData && 'blur-sm select-none')}>
                      {!showRawData ? (
                        '****'
                      ) : t.deltaUnit === 'bp' ? (
                      <>
                        Δ5d {formatSigned(t.delta5Pct, 0, 'bp')} • Δ20d {formatSigned(t.delta20Pct, 0, 'bp')}
                      </>
                    ) : (
                      <>
                        Δ5d {formatSigned(t.delta5Pct, 2, '%')} • Δ20d {formatSigned(t.delta20Pct, 2, '%')}
                        {(t.showRv ?? true) && (
                          <>
                            {' • '}rv20 {t.rv20Pct == null ? '-' : `${formatNumberValue(t.rv20Pct, 1)}%`}
                          </>
                        )}
                      </>
                    )}
                  </div>
                </div>
                <div className="w-full min-w-0 sm:w-[40%] sm:min-w-[120px] sm:max-w-[170px]">
                  <div className={cn(!showRawData && 'blur-sm select-none')}>
                    <ResponsiveSparklineMini data={t.spark} height={56} color="#64748b" label={t.key} minWidth={0} />
                  </div>
                </div>
              </div>
              {!showRawData ? (
                <RedactedOverlay badgeClassName="text-[10px]" />
              ) : null}
            </div>
          ))}
        </div>
      )}
      </CardContent>
    </Card>
  )
}
