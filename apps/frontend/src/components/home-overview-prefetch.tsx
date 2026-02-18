'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FIVE_MIN_MS } from '@/lib/time'
import { Skeleton } from '@/components/ui/skeleton'

const isClient = typeof window !== 'undefined'

type Part<T> = { ok: true; data: T } | { ok: false; status: number; error: string }

type NowcastOverviewResponse = {
  nowcastLatest?: Part<unknown>
  nowcastLatestV2?: Part<unknown>
  regimeRulesLatest?: Part<unknown>
  macroLiquidityLatest?: Part<unknown>
  hyStressLatest?: Part<unknown>
  volRegimeLatest?: Part<unknown>
}

type MacroOverviewResponse = {
  macroLiquidityLatest?: Part<unknown>
  macroLiquiditySeriesRrp?: Part<unknown>
  macroLiquiditySeriesTga?: Part<unknown>
  macroNetLiquidityLatest?: Part<unknown>
  macroNetLiquiditySeries?: Part<unknown>
  hyStressLatest?: Part<unknown>
  hyStressSeries?: Part<unknown>
  fraOisLatest?: Part<unknown>
  fraOisSeries36?: Part<unknown>
  volRegimeLatest?: Part<unknown>
  macroPutCallEquitySeries?: Part<unknown>
  macroPutCallSpxSeries?: Part<unknown>
  benchmarkSeriesUsdx?: Part<unknown>
  benchmarkSeriesXau?: Part<unknown>
  benchmarkSeriesWti?: Part<unknown>
  treasurySeries2y?: Part<unknown>
  treasurySeries10y?: Part<unknown>
  treasurySeriesOn?: Part<unknown>
  tips10ySeries?: Part<unknown>
  pricesHistoryTlt?: Part<unknown>
  pricesHistoryEmb?: Part<unknown>
  fxSeriesUsdjpy?: Part<unknown>
  fxSeriesCnyusd?: Part<unknown>
  breadthLatest?: Part<unknown>
  breadthSeriesSpxExposure?: Part<unknown>
  breadthSeriesNdxExposure?: Part<unknown>
  breadthSeriesNyseAd?: Part<unknown>
  moneyFlowSectors?: Part<unknown>
  moneyFlowSectorSeries?: Part<unknown>
}

type RegimeOverviewResponse = {
  rankRegimeLatest?: Part<unknown>
  rankRegimeHistory180?: Part<unknown>
  marketStructureLatest?: Part<unknown>
  marketStructureSeries180?: Part<unknown>
  regimeLatestIntensity?: Part<unknown>
  regimeLatestRules?: Part<unknown>
  regimeSeries180?: Part<unknown>
  regimeRulesSeries180?: Part<unknown>
  screenerBreadthFlow120?: Part<unknown>
}

function isOk<T>(part: Part<T> | undefined): part is { ok: true; data: T } {
  return Boolean(part && part.ok)
}

function OverviewSectionSkeleton({ height = 420 }: { height?: number }) {
  return <Skeleton className="w-full rounded-2xl" style={{ height }} />
}

function OverviewNowcastSkeleton() {
  return (
    <div className="space-y-4">
      <OverviewSectionSkeleton height={120} />
      <OverviewSectionSkeleton height={420} />
    </div>
  )
}

function OverviewRegimeSkeleton() {
  return <OverviewSectionSkeleton height={520} />
}

function seedNowcastOverviewCache(queryClient: ReturnType<typeof useQueryClient>, payload: NowcastOverviewResponse) {
  const set = (queryKey: unknown[], part: Part<unknown> | undefined) => {
    if (!isOk(part)) return
    queryClient.setQueryData(queryKey, part.data)
  }

  set(['overview', 'headlines', 'nowcast-latest'], payload.nowcastLatest)
  set(['overview', 'headlines', 'regime-rules-latest'], payload.regimeRulesLatest)
  set(['overview', 'headlines', 'liquidity-latest'], payload.macroLiquidityLatest)
  set(['overview', 'headlines', 'hy-stress-latest'], payload.hyStressLatest)
  set(['overview', 'headlines', 'vol-regime-latest'], payload.volRegimeLatest)
  set(['nowcast', 'latest', 'nowcast_v2'], payload.nowcastLatestV2)
}

function seedMacroOverviewCache(queryClient: ReturnType<typeof useQueryClient>, payload: MacroOverviewResponse) {
  const set = (queryKey: unknown[], part: Part<unknown> | undefined) => {
    if (!isOk(part)) return
    queryClient.setQueryData(queryKey, part.data)
  }

  set(['macro', 'liquidity', 'latest'], payload.macroLiquidityLatest)
  set(['macro', 'liquidity', 'series', 'on_rrp'], payload.macroLiquiditySeriesRrp)
  set(['macro', 'liquidity', 'series', 'tga'], payload.macroLiquiditySeriesTga)
  set(['macro', 'liquidity', 'net-liquidity', 'latest'], payload.macroNetLiquidityLatest)
  set(['macro', 'liquidity', 'net-liquidity', 'series'], payload.macroNetLiquiditySeries)
  set(['risk', 'hy-stress', 'latest'], payload.hyStressLatest)
  set(['risk', 'hy-stress', 'series'], payload.hyStressSeries)
  set(['rates', 'fra-ois', 'latest'], payload.fraOisLatest)
  set(['rates', 'fra-ois', 'series', '3x6'], payload.fraOisSeries36)
  set(['macro', 'vol-regime', 'latest'], payload.volRegimeLatest)
  set(['macro', 'put-call', 'series', 'equity'], payload.macroPutCallEquitySeries)
  set(['macro', 'put-call', 'series', 'spx'], payload.macroPutCallSpxSeries)
  set(['benchmarks', 'series', '$USDX'], payload.benchmarkSeriesUsdx)
  set(['benchmarks', 'series', 'XAUUSD'], payload.benchmarkSeriesXau)
  set(['benchmarks', 'series', '@WTI'], payload.benchmarkSeriesWti)
  set(['rates', 'treasury', 'series', '2Y'], payload.treasurySeries2y)
  set(['rates', 'treasury', 'series', '10Y'], payload.treasurySeries10y)
  set(['rates', 'treasury', 'series', 'O/N'], payload.treasurySeriesOn)
  set(['macro', 'real-rates', 'tips10y', 'series'], payload.tips10ySeries)
  set(['prices', 'history', 'TLT'], payload.pricesHistoryTlt)
  set(['prices', 'history', 'EMB'], payload.pricesHistoryEmb)
  set(['fx', 'series', 'USDJPY'], payload.fxSeriesUsdjpy)
  set(['fx', 'series', 'CNYUSD'], payload.fxSeriesCnyusd)
  set(['breadth', 'latest'], payload.breadthLatest)
  set(['breadth', 'series', 'SPX', 'target_exposure'], payload.breadthSeriesSpxExposure)
  set(['breadth', 'series', 'NDX', 'target_exposure'], payload.breadthSeriesNdxExposure)
  set(['breadth', 'series', 'NYSE', 'ad_ratio'], payload.breadthSeriesNyseAd)
  set(['money-flow', 'sectors', 'latest'], payload.moneyFlowSectors)
  set(['money-flow', 'sectors', 'series'], payload.moneyFlowSectorSeries)
}

function seedRegimeOverviewCache(queryClient: ReturnType<typeof useQueryClient>, payload: RegimeOverviewResponse) {
  const set = (queryKey: unknown[], part: Part<unknown> | undefined) => {
    if (!isOk(part)) return
    queryClient.setQueryData(queryKey, part.data)
  }

  set(['rank-regime-latest'], payload.rankRegimeLatest)
  set(['rank-regime-history', 180], payload.rankRegimeHistory180)
  set(['market-structure-latest'], payload.marketStructureLatest)
  set(['market-structure-series', 180], payload.marketStructureSeries180)
  set(['regime-latest-intensity'], payload.regimeLatestIntensity)
  set(['regime-latest-rules'], payload.regimeLatestRules)
  set(['regime-series', 180], payload.regimeSeries180)
  set(['regime-rules-series', 180], payload.regimeRulesSeries180)
  set(['screener-breadth-flow', 120], payload.screenerBreadthFlow120)
}

export const NOWCAST_OVERVIEW_QUERY_KEY = ['overview', 'nowcast'] as const
const NOWCAST_OVERVIEW_SEEDED_KEY = ['overview', 'nowcast', 'seeded'] as const

export function OverviewNowcastPrefetch({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const seededOnceRef = useRef(false)
  const macroPrefetchRef = useRef(false)
  const [seeded, setSeeded] = useState(() => Boolean(queryClient.getQueryData(NOWCAST_OVERVIEW_SEEDED_KEY)))

  const { data, isError } = useQuery<NowcastOverviewResponse>({
    queryKey: NOWCAST_OVERVIEW_QUERY_KEY,
    enabled: isClient && !seeded,
    queryFn: async ({ signal }) => {
      const res = await fetch('/api/overview/nowcast', { signal })
      if (!res.ok) throw new Error(`Failed to load overview nowcast: ${res.status}`)
      return (await res.json()) as NowcastOverviewResponse
    },
    staleTime: FIVE_MIN_MS,
    gcTime: 30 * 60_000,
  })

  useEffect(() => {
    if (!data || seededOnceRef.current) return
    seedNowcastOverviewCache(queryClient, data)
    seededOnceRef.current = true
    queryClient.setQueryData(NOWCAST_OVERVIEW_SEEDED_KEY, true)
    setSeeded(true)
  }, [data, queryClient])

  useEffect(() => {
    if (macroPrefetchRef.current) return
    if (queryClient.getQueryData(MACRO_OVERVIEW_SEEDED_KEY)) return
    macroPrefetchRef.current = true

    queryClient
      .fetchQuery({
        queryKey: MACRO_OVERVIEW_QUERY_KEY,
        queryFn: async ({ signal }) => {
          const res = await fetch('/api/overview/macro', { signal })
          if (!res.ok) throw new Error(`Failed to prefetch overview macro: ${res.status}`)
          return (await res.json()) as MacroOverviewResponse
        },
        staleTime: FIVE_MIN_MS,
        gcTime: 30 * 60_000,
      })
      .then((payload) => {
        seedMacroOverviewCache(queryClient, payload)
        queryClient.setQueryData(MACRO_OVERVIEW_SEEDED_KEY, true)
      })
      .catch(() => {
        macroPrefetchRef.current = false
      })
  }, [queryClient])

  if (isError) {
    return <>{children}</>
  }

  if (!seeded) {
    return <OverviewNowcastSkeleton />
  }

  return <>{children}</>
}

export const MACRO_OVERVIEW_QUERY_KEY = ['overview', 'macro'] as const
const MACRO_OVERVIEW_SEEDED_KEY = ['overview', 'macro', 'seeded'] as const

export function OverviewMacroPrefetch({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const seededOnceRef = useRef(false)
  const [seeded, setSeeded] = useState(() => Boolean(queryClient.getQueryData(MACRO_OVERVIEW_SEEDED_KEY)))

  const { data, isError } = useQuery<MacroOverviewResponse>({
    queryKey: MACRO_OVERVIEW_QUERY_KEY,
    enabled: isClient && !seeded,
    queryFn: async ({ signal }) => {
      const res = await fetch('/api/overview/macro', { signal })
      if (!res.ok) throw new Error(`Failed to load overview macro: ${res.status}`)
      return (await res.json()) as MacroOverviewResponse
    },
    staleTime: FIVE_MIN_MS,
    gcTime: 30 * 60_000,
  })

  useEffect(() => {
    if (!data || seededOnceRef.current) return
    seedMacroOverviewCache(queryClient, data)
    seededOnceRef.current = true
    queryClient.setQueryData(MACRO_OVERVIEW_SEEDED_KEY, true)
    setSeeded(true)
  }, [data, queryClient])

  if (isError) {
    return <>{children}</>
  }

  if (!seeded) {
    return <OverviewRegimeSkeleton />
  }

  return <>{children}</>
}

export const REGIME_OVERVIEW_QUERY_KEY = ['overview', 'regime'] as const
const REGIME_OVERVIEW_SEEDED_KEY = ['overview', 'regime', 'seeded'] as const

export function OverviewRegimePrefetch({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const seededOnceRef = useRef(false)
  const [seeded, setSeeded] = useState(() => Boolean(queryClient.getQueryData(REGIME_OVERVIEW_SEEDED_KEY)))

  const { data, isError } = useQuery<RegimeOverviewResponse>({
    queryKey: REGIME_OVERVIEW_QUERY_KEY,
    enabled: isClient && !seeded,
    queryFn: async ({ signal }) => {
      const res = await fetch('/api/overview/regime', { signal })
      if (!res.ok) throw new Error(`Failed to load overview regime: ${res.status}`)
      return (await res.json()) as RegimeOverviewResponse
    },
    staleTime: FIVE_MIN_MS,
    gcTime: 30 * 60_000,
  })

  useEffect(() => {
    if (!data || seededOnceRef.current) return
    seedRegimeOverviewCache(queryClient, data)
    seededOnceRef.current = true
    queryClient.setQueryData(REGIME_OVERVIEW_SEEDED_KEY, true)
    setSeeded(true)
  }, [data, queryClient])

  if (isError) {
    return <>{children}</>
  }

  return <>{children}</>
}
