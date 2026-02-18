'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, EmptyResponse, HyStressLatestResponse, NowcastLatestResponse, VolRegimeResponse } from '@/lib/api'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { isEmptyResponse } from '@/lib/nowcast-utils'
import { FIVE_MIN_MS } from '@/lib/time'

function toneForLabel(label?: string | null): BadgeProps['variant'] {
  const v = (label || '').toLowerCase()
  if (v.includes('risk_off') || v.includes('crisis') || v.includes('stressed') || v.includes('panic')) return 'danger'
  if (v.includes('risk_on') || v.includes('easy') || v.includes('calm')) return 'success'
  if (v.includes('transition') || v.includes('fragile') || v.includes('warning') || v.includes('mixed')) return 'warning'
  return 'secondary'
}

function nowcastLabelPretty(label?: string | null) {
  if (!label) return '-'
  const v = label.replace(/_/g, ' ')
  return v.charAt(0).toUpperCase() + v.slice(1)
}

function regimePretty(label?: string | null) {
  if (!label) return '-'
  return label
}

export function HeadlinesStrip() {
  const { data: nowcastLatest, isLoading: nowcastLoading } = useQuery<NowcastLatestResponse>({
    queryKey: ['overview', 'headlines', 'nowcast-latest'],
    queryFn: () => api.getNowcastLatest({ trail_days: 30 }),
    staleTime: FIVE_MIN_MS,
  })

  const { data: regimeRulesLatest, isLoading: regimeLoading } = useQuery({
    queryKey: ['overview', 'headlines', 'regime-rules-latest'],
    queryFn: () => api.getRegimeRulesLatest(),
    staleTime: FIVE_MIN_MS,
  })

  const { data: liquidityLatest, isLoading: liquidityLoading } = useQuery({
    queryKey: ['overview', 'headlines', 'liquidity-latest'],
    queryFn: () => api.getMacroLiquidityLatest(),
    staleTime: FIVE_MIN_MS,
  })

  const { data: hyLatest, isLoading: hyLoading } = useQuery<HyStressLatestResponse>({
    queryKey: ['overview', 'headlines', 'hy-stress-latest'],
    queryFn: () => api.getHyStressLatest(),
    staleTime: FIVE_MIN_MS,
  })

  const { data: volRegime, isLoading: volLoading } = useQuery<VolRegimeResponse>({
    queryKey: ['overview', 'headlines', 'vol-regime-latest'],
    queryFn: () => api.getVolRegimeLatest(),
    staleTime: FIVE_MIN_MS,
  })

  const nowcast = useMemo(() => {
    if (!nowcastLatest || isEmptyResponse(nowcastLatest)) return null
    return nowcastLatest as Exclude<NowcastLatestResponse, EmptyResponse>
  }, [nowcastLatest])

  const rules = useMemo(() => {
    if (!regimeRulesLatest || isEmptyResponse(regimeRulesLatest)) return null
    return regimeRulesLatest as any
  }, [regimeRulesLatest])

  const liq = useMemo(() => {
    if (!liquidityLatest || isEmptyResponse(liquidityLatest)) return null
    return liquidityLatest as any
  }, [liquidityLatest])

  const hy = useMemo(() => {
    if (!hyLatest || isEmptyResponse(hyLatest)) return null
    return hyLatest as Exclude<HyStressLatestResponse, EmptyResponse>
  }, [hyLatest])

  const vr = useMemo(() => {
    if (!volRegime || isEmptyResponse(volRegime)) return null
    return volRegime as any
  }, [volRegime])

  const items = [
    {
      label: 'Nowcast',
      value: nowcast ? nowcastLabelPretty(nowcast.nowcast_label) : null,
      tone: nowcast ? toneForLabel(nowcast.nowcast_label || 'mixed') : 'secondary',
      loading: nowcastLoading,
    },
    {
      label: 'Regime',
      value: rules?.label ? regimePretty(rules.label) : null,
      tone: rules?.label ? toneForLabel(rules.label) : 'secondary',
      loading: regimeLoading,
    },
    {
      label: 'Liquidity',
      value: liq?.regime ? liq.regime.replace(/_/g, ' ') : null,
      tone: liq?.regime ? toneForLabel(liq.regime) : 'secondary',
      loading: liquidityLoading,
    },
    {
      label: 'Credit',
      value: hy?.label ? hy.label.replace(/_/g, ' ') : null,
      tone: hy?.label ? toneForLabel(hy.label) : 'secondary',
      loading: hyLoading,
    },
    {
      label: 'Vol',
      value: vr?.vol_state ? String(vr.vol_state) : null,
      tone: vr?.vol_state ? toneForLabel(vr.vol_state) : 'secondary',
      loading: volLoading,
    },
    {
      label: 'VRP',
      value: vr?.vrp_state ? String(vr.vrp_state) : null,
      tone: vr?.vrp_state ? toneForLabel(vr.vrp_state) : 'secondary',
      loading: volLoading,
    },
  ] as const

  return (
    <div className="rounded-2xl border border-outline/10 bg-card p-3">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Headlines</div>
        <div className="text-[11px] text-muted-foreground">What’s the regime + what changed?</div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:flex sm:overflow-x-auto sm:pb-1">
        {items.map((it) => (
          <div
            key={it.label}
            className={cn(
              'min-w-0 rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2 sm:min-w-[160px]',
              'flex items-start justify-between gap-2',
            )}
          >
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{it.label}</div>
              <div className="mt-1">
                {it.loading ? (
                  <Skeleton className="h-5 w-24" />
                ) : (
                  <Badge variant={it.tone as BadgeProps['variant']} className="text-xs font-semibold">
                    {it.value ?? '-'}
                  </Badge>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
