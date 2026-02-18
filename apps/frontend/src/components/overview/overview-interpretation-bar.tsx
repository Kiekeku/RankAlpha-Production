'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  api,
  type EmptyResponse,
  type NowcastLatestResponse,
  type NowcastLabel,
  type NowcastDriver,
  type NowcastPillarKey,
  type RegimeRulesLatest,
} from '@/lib/api'
import { formatEasternDate } from '@/lib/date'
import { formatSigned } from '@/lib/nowcast-utils'
import { Skeleton } from '@/components/ui/skeleton'
import { LoadingStatusNote } from '@/components/loading-status-note'
import { cn } from '@/lib/utils'
import { buildOverviewImplication } from '@/components/overview/overview-interpretation'

type InterpretationLine = {
  label: string
  value: string
}

function isNowcast(data: NowcastLatestResponse | undefined): data is Exclude<NowcastLatestResponse, { status: 'empty' }> {
  return Boolean(data && !('status' in data))
}

function isRegimeRules(data: RegimeRulesLatest | EmptyResponse | undefined): data is RegimeRulesLatest {
  return Boolean(data && !('status' in data))
}

function prettyNowcast(label?: NowcastLabel | null) {
  if (!label) return null
  if (label === 'risk_on') return 'Risk-On'
  if (label === 'risk_off') return 'Risk-Off'
  return 'Mixed'
}

function prettyRegime(label?: string | null) {
  if (!label) return null
  return label
}

const DRIVER_LABELS: Record<NowcastPillarKey, string> = {
  liquidity: 'Liquidity',
  vol_tail: 'Stress',
  funding: 'Funding',
  credit: 'Credit',
  rates_usd: 'Rates',
  breadth: 'Breadth',
  flows: 'Flows',
}

function driverLabel(driver: NowcastDriver) {
  return DRIVER_LABELS[driver.pillar_key] ?? driver.title ?? 'Signal'
}

function buildDriverSummary(drivers: NowcastDriver[] | undefined) {
  if (!drivers || !drivers.length) return null
  const ranked = [...drivers]
    .filter((d) => d.impact != null && Number.isFinite(d.impact))
    .sort((a, b) => Math.abs(Number(b.impact)) - Math.abs(Number(a.impact)))
    .slice(0, 2)

  if (!ranked.length) return null
  return ranked
    .map((d) => `${driverLabel(d)} ${Number(d.impact) > 0 ? '↑' : '↓'}`)
    .join(', ')
}

export function OverviewInterpretationBar({ className }: { className?: string }) {
  const { data: nowcastData, isLoading: nowcastLoading } = useQuery({
    queryKey: ['nowcast', 'latest', 'nowcast_v2', 'interpretation'],
    queryFn: () => api.getNowcastLatest({ model_version: 'nowcast_v2', trail_days: 5 }),
    staleTime: 5 * 60 * 1000,
  })

  const { data: regimeRules, isLoading: regimeLoading } = useQuery({
    queryKey: ['regime-rules-latest', 'interpretation'],
    queryFn: () => api.getRegimeRulesLatest(),
    staleTime: 5 * 60 * 1000,
  })

  const content = useMemo(() => {
    const nowcast = isNowcast(nowcastData) ? nowcastData : null
    const rules = isRegimeRules(regimeRules) ? regimeRules : null
    const nowcastLabel = prettyNowcast(nowcast?.nowcast_label ?? null)
    const regimeLabel = prettyRegime(rules?.label ?? null)
    const asOf = nowcast?.as_of_date ? formatEasternDate(nowcast.as_of_date) : null

    const currentBits = [
      nowcastLabel ? nowcastLabel : null,
      regimeLabel ? `${regimeLabel} regime` : null,
    ].filter(Boolean)

    const current = currentBits.length ? currentBits.join(' · ') : 'Signals updating'

    const driverSummary = buildDriverSummary(nowcast?.drivers)
    const change = driverSummary
      ? driverSummary
      : nowcast?.delta_1d != null
        ? `Risk-off score Δ1d ${formatSigned(nowcast.delta_1d, 1)}`
        : nowcast?.label_1d_ago && nowcast?.nowcast_label && nowcast.label_1d_ago !== nowcast.nowcast_label
          ? `Label shift: ${prettyNowcast(nowcast.label_1d_ago)} → ${prettyNowcast(nowcast.nowcast_label)}`
          : 'No meaningful delta flagged'

    const implication = buildOverviewImplication({
      nowcast_label: nowcast?.nowcast_label ?? null,
      overall_risk_off_score: nowcast?.overall_risk_off_score ?? null,
      confidence: nowcast?.confidence ?? null,
      coverage: nowcast?.coverage ?? null,
      delta_1d: nowcast?.delta_1d ?? null,
      delta_5d: nowcast?.delta_5d ?? null,
      cross_asset_label: nowcast?.cross_asset_label ?? null,
      regime_rules_label: rules?.label ?? null,
      regime_rules_tags: rules?.tags ?? null,
    })

    const lines: InterpretationLine[] = [
      { label: 'Current state', value: current },
      { label: 'What changed', value: change },
      { label: 'Implication', value: implication },
    ]

    return { lines, asOf }
  }, [nowcastData, regimeRules])

  return (
    <div className={cn('sticky top-24 z-20', className)}>
      <div className="rounded-2xl border border-outline/10 bg-card/90 px-4 py-3 shadow-sm backdrop-blur">
        {nowcastLoading || regimeLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-3 w-[60%]" />
            <Skeleton className="h-3 w-[80%]" />
            <Skeleton className="h-3 w-[70%]" />
            <LoadingStatusNote label="Loading overview context…" className="pt-1" />
          </div>
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1 text-[11px] sm:text-xs">
              {content.lines.map((line) => (
                <div key={line.label} className="flex flex-wrap items-baseline gap-2">
                  <span className="text-muted-foreground">{line.label}:</span>
                  <span className="font-semibold text-foreground">{line.value}</span>
                </div>
              ))}
            </div>
            {content.asOf ? (
              <div className="text-[11px] text-muted-foreground">As of {content.asOf}</div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
