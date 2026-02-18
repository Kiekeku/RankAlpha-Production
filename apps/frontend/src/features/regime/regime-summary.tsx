'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { ChartCard } from '@/components/dashboard/chart-card'
import { InfoTooltipButton } from '@/components/info_tooltip_button'
import { api, type NowcastLatestResponse, type NowcastPillar } from '@/lib/api'
import { formatSigned } from '@/lib/nowcast-utils'
import { cn } from '@/lib/utils'
import { useMethodology } from '@/components/methodology/methodology_context'
import { TooltipCopy, TooltipCopyButton } from '@/components/tooltip_copy'
import { DataStateWrapper } from '@/components/data-state-wrapper'

import { formatPct } from './regime-shared'

type RiskNowcastLabel = 'risk_on' | 'neutral' | 'risk_off'
type RiskMapPoint = { date: string; liquidity: number; stress: number }

function clampNumber(value: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, value))
}

function formatMaybeNumber(value?: number | null, digits = 2) {
  if (value == null || !Number.isFinite(value)) return '-'
  return Number(value).toFixed(digits)
}

function scoreTone(score?: number | null): BadgeProps['variant'] {
  if (score == null || !Number.isFinite(score)) return 'secondary'
  if (score >= 80) return 'danger'
  if (score >= 70) return 'warning'
  if (score <= 20) return 'success'
  if (score <= 30) return 'info'
  return 'secondary'
}

function prettyNowcast(label: RiskNowcastLabel) {
  if (label === 'risk_off') return 'Risk-Off'
  if (label === 'risk_on') return 'Risk-On'
  return 'Mixed'
}

function nowcastTextClass(label: RiskNowcastLabel) {
  if (label === 'risk_off') return 'text-status-danger'
  if (label === 'risk_on') return 'text-status-success'
  return 'text-status-warning-foreground'
}

function RiskMapMini({
  points,
  width = 320,
  height = 180,
}: {
  points: RiskMapPoint[]
  width?: number
  height?: number
}) {
  const padding = 18
  const innerW = width - padding * 2
  const innerH = height - padding * 2
  const toX = (v: number) => padding + (clampNumber(v, 0, 100) / 100) * innerW
  const toY = (v: number) => padding + innerH - (clampNumber(v, 0, 100) / 100) * innerH

  const last = points[points.length - 1]
  const path = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(p.liquidity).toFixed(1)},${toY(p.stress).toFixed(1)}`)
    .join(' ')

  const ticks = [0, 100 / 3, 200 / 3, 100]

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" aria-label="Liquidity vs stress map">
      <rect x={0} y={0} width={width} height={height} rx={16} fill="transparent" />

      {ticks.map((t, idx) => (
        <g key={t}>
          <line
            x1={toX(t)}
            y1={toY(0)}
            x2={toX(t)}
            y2={toY(100)}
            stroke="hsl(var(--outline) / 0.10)"
            strokeWidth={1}
            opacity={idx === 0 || idx === ticks.length - 1 ? 0.45 : 0.75}
          />
          <line
            x1={toX(0)}
            y1={toY(t)}
            x2={toX(100)}
            y2={toY(t)}
            stroke="hsl(var(--outline) / 0.10)"
            strokeWidth={1}
            opacity={idx === 0 || idx === ticks.length - 1 ? 0.45 : 0.75}
          />
        </g>
      ))}

      <text x={padding} y={14} fontSize={10} fill="hsl(var(--muted-foreground))">
        Stress ↑
      </text>
      <text
        x={width - padding}
        y={height - 6}
        fontSize={10}
        fill="hsl(var(--muted-foreground))"
        textAnchor="end"
      >
        Liquidity → (easier)
      </text>

      {points.length > 1 ? <path d={path} fill="none" stroke="hsl(var(--status-info))" strokeWidth={2} opacity={0.9} /> : null}
      {points.map((p, i) => (
        <circle
          key={`${p.date}-${i}`}
          cx={toX(p.liquidity)}
          cy={toY(p.stress)}
          r={i === points.length - 1 ? 3.6 : 2}
          fill={i === points.length - 1 ? 'hsl(var(--background))' : 'hsl(var(--status-info))'}
          stroke={i === points.length - 1 ? 'hsl(var(--status-info))' : 'none'}
          strokeWidth={i === points.length - 1 ? 1.25 : 0}
          opacity={i === points.length - 1 ? 0.95 : 0.45}
        />
      ))}
      {last ? (
        <text x={padding + 2} y={height - padding + 10} fontSize={10} fill="hsl(var(--muted-foreground))">
          {last.date}
        </text>
      ) : null}
    </svg>
  )
}

function PillarCard({
  title,
  score,
  scoreText,
  primary,
  secondary,
  tooltip,
}: {
  title: string
  score?: number | null
  scoreText?: string
  primary: string
  secondary?: string
  tooltip?: string
}) {
  return (
    <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
          <p className="mt-1 truncate text-sm font-semibold">{primary}</p>
          {secondary ? <p className="mt-0.5 truncate text-xs text-muted-foreground">{secondary}</p> : null}
        </div>
        <div className="flex items-center gap-2">
          {tooltip ? <InfoTooltipButton label={title} description={tooltip} iconSize="h-3.5 w-3.5" /> : null}
          <Badge variant={scoreTone(score)} className="shrink-0 px-2 py-1 text-xs">
            {scoreText ?? (score == null ? '-' : `${Math.round(score)}`)}
          </Badge>
        </div>
      </div>
    </div>
  )
}

function isNowcast(latest: NowcastLatestResponse | undefined): latest is Exclude<NowcastLatestResponse, { status: 'empty' }> {
  return Boolean(latest && !('status' in latest))
}

export function RegimeSummary() {
  const methodology = useMethodology()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['nowcast', 'latest', 'nowcast_v2'],
    queryFn: () => api.getNowcastLatest({ model_version: 'nowcast_v2', trail_days: 60 }),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })

  const nowcast = isNowcast(data) ? data : null

  const mapPoints = useMemo<RiskMapPoint[]>(() => {
    const items = nowcast?.map_trail ?? []
    const points = items
      .filter((p) => p.as_of_date && p.liquidity_ease != null && p.stress_score != null)
      .map((p) => ({
        date: String(p.as_of_date).slice(5),
        liquidity: Number(p.liquidity_ease),
        stress: Number(p.stress_score),
      }))
      .filter((p) => Number.isFinite(p.liquidity) && Number.isFinite(p.stress))
    return points
  }, [nowcast])

  if (isLoading) {
    return (
      <ChartCard
        title="Daily Risk Nowcast"
        description="Equity drawdown risk (headline) + cross-asset stress (peripheral)."
        contentClassName="space-y-ds-4"
      >
        <DataStateWrapper
          status="loading"
          context="overview-nowcast"
          size="compact"
          loadingLabel="Loading Nowcast…"
        />
      </ChartCard>
    )
  }

  if (isError) {
    return (
      <ChartCard title="Risk Nowcast" description="Unable to load nowcast snapshot.">
        <DataStateWrapper
          status="error"
          context="overview-nowcast"
          message="Try refreshing, or check back after the next pipeline run."
          size="compact"
        />
      </ChartCard>
    )
  }

  if (!nowcast) {
    return (
      <ChartCard title="Risk Nowcast" description="No nowcast snapshot available yet.">
        <DataStateWrapper
          status="empty"
          context="overview-nowcast"
          message="This view is driven by nightly DB snapshots. Once the pipeline runs and writes the snapshot, it will appear here."
          tips={['Check back after the next pipeline refresh.']}
          size="compact"
        />
      </ChartCard>
    )
  }

  const overall = nowcast.overall_risk_off_score
  const label = (nowcast.nowcast_label || 'neutral') as RiskNowcastLabel
  const crossLabel = (nowcast.cross_asset_label || 'neutral') as RiskNowcastLabel

  const pillarViews = nowcast.pillars ?? []
  const drivers = nowcast.drivers ?? []
  const alerts = nowcast.alerts ?? []

  const pillarCardText = (p: NowcastPillar) => {
    switch (p.pillar_key) {
      case 'liquidity': {
        const d = p.details
        return {
          primary: d.regime_label ? String(d.regime_label) : '-',
          secondary:
            d.net_liquidity_trn == null
              ? undefined
              : `NetLiq ${formatSigned(d.net_liquidity_trn, 2, 'T')} • Δ4w ${formatSigned(d.delta_4w_trn, 2, 'T')} • Δ13w ${formatSigned(
                  d.delta_13w_trn,
                  2,
                  'T'
                )}`,
        }
      }
      case 'vol_tail': {
        const d = p.details
        return {
          primary: d.vix_1m == null ? '-' : `${formatMaybeNumber(d.vix_1m, 1)} VIX1M`,
          secondary: d.skew_z == null ? undefined : `SKEW z ${formatMaybeNumber(d.skew_z, 2)} • level ${formatMaybeNumber(d.skew, 1)}`,
        }
      }
      case 'funding': {
        const d = p.details
        return {
          primary: d.fra_ois_z == null ? '-' : `${formatMaybeNumber(d.fra_ois_z, 2)} z`,
          secondary: d.spread_bp == null ? undefined : `3x6 spread ${formatSigned(d.spread_bp, 1, 'bp')}`,
        }
      }
      case 'credit': {
        const d = p.details
        return {
          primary: d.hy_stress_z == null ? '-' : `${formatMaybeNumber(d.hy_stress_z, 2)} z`,
          secondary: d.hy_stress_ma == null ? undefined : `MA ${formatMaybeNumber(d.hy_stress_ma, 2)} • ${d.benchmark_name ?? '%CCCHYS'}`,
        }
      }
      case 'rates_usd': {
        const d = p.details
        return {
          primary:
            d.y10_shock_bp == null ? '-' : `Rate shock ${formatMaybeNumber(d.y10_shock_bp, 0)}bp (max |Δ5d|,|Δ20d|)`,
          secondary:
            d.slope_2s10s == null
              ? undefined
              : `2s10s ${formatSigned(d.slope_2s10s * 100, 0, 'bp')} • USDX z ${d.usdx_z == null ? '-' : formatMaybeNumber(d.usdx_z, 2)}`,
        }
      }
      case 'breadth': {
        const d = p.details
        return {
          primary: d.target_exposure == null ? '-' : formatPct(d.target_exposure),
          secondary: 'SPX target exposure',
        }
      }
      case 'flows': {
        const d = p.details
        return {
          primary: d.appetite == null ? '-' : `${formatSigned(d.appetite, 2)} (cyc−def)`,
          secondary: d.appetite_z == null ? undefined : `z ${formatMaybeNumber(d.appetite_z, 2)}`,
        }
      }
      default:
        return { primary: '-', secondary: undefined }
    }
  }

  return (
    <ChartCard
      title="Daily Risk Nowcast"
      description="Equity drawdown risk (headline) + cross-asset stress (peripheral)."
    >
	          <div className="grid gap-5 lg:grid-cols-2">
	            <div className="space-y-4">
	              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
	                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
	                  <div>
	                    <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        <span>Nowcast</span>
                        <TooltipCopyButton
                          tooltipKey="overview.riskNowcast"
                          iconSize="h-3.5 w-3.5"
                          buttonClassName="text-muted-foreground hover:text-foreground"
                        />
                      </p>
	                    <p className={cn('mt-1 text-2xl font-semibold', nowcastTextClass(label))}>{prettyNowcast(label)}</p>
	                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <TooltipCopy tooltipKey="nowcast.riskOffScore">
                      <Badge variant={scoreTone(overall)} className="px-2 py-1">
                        {overall == null ? '-' : `${Math.round(overall)}`}
                      </Badge>
                    </TooltipCopy>
                    <span>Δ1d {nowcast.delta_1d == null ? '-' : formatSigned(nowcast.delta_1d, 1)}</span>
                    <span>Δ5d {nowcast.delta_5d == null ? '-' : formatSigned(nowcast.delta_5d, 1)}</span>
                    {nowcast.label_1d_ago ? (
                      <span>Prev {prettyNowcast(nowcast.label_1d_ago as RiskNowcastLabel)}</span>
	                    ) : null}
	                  </div>
	                </div>
	
	                <div className="sm:text-right">
	                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Confidence</p>
	                  <p className="mt-1 text-2xl font-semibold">{nowcast.confidence == null ? '-' : `${Math.round(nowcast.confidence * 100)}%`}</p>
	                  <p className="mt-1 text-xs text-muted-foreground">
	                    Coverage {nowcast.coverage == null ? '-' : `${Math.round(nowcast.coverage * 100)}%`}
                  </p>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  Cross-asset: {prettyNowcast(crossLabel)} {nowcast.cross_asset_stress_score == null ? '' : `(${Math.round(nowcast.cross_asset_stress_score)})`}
                </Badge>
                {nowcast.booster_applied ? (
                  <Badge variant="secondary" className="text-xs">
                    No-hiding-place +{nowcast.booster_amount == null ? '-' : Math.round(nowcast.booster_amount)}
                  </Badge>
                ) : null}
              </div>

              {drivers.length ? (
                <div className="mt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Top drivers</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {drivers.map((d) => (
                      <Badge key={String(d.pillar_key)} variant={scoreTone(d.score)} className="px-2 py-1 text-xs">
                        {d.title ?? d.pillar_key}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Alerts</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {alerts.length ? (
                    alerts.map((a) => (
                      <Badge key={String(a.pillar_key)} variant={scoreTone(a.score)} className="px-2 py-1 text-xs">
                        {a.title ?? a.pillar_key}: {a.severity}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">No active extreme flags.</span>
                  )}
                </div>
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pillars (risk-off score)</p>
                <InfoTooltipButton
                  label="Pillars"
                  iconSize="h-3.5 w-3.5"
                  description="Each pillar is mapped to a simple 0–100 risk-off score to make heterogeneous measures comparable."
                  learnMore={{ label: 'Methodology', onClick: () => methodology.open('nowcast') }}
                />
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {pillarViews.map((p) => {
                  const t = pillarCardText(p)
                  const scoreText =
                    p.pillar_key === 'flows' && p.score == null && p.details.appetite != null ? 'n/a' : undefined
                  const tooltip =
                    p.pillar_key === 'flows' && p.score == null && p.details.appetite != null
                      ? 'Risk-off score is unavailable until enough daily history exists to z-score sector money-flow appetite.'
                      : undefined
                  return (
                    <PillarCard
                      key={p.pillar_key}
                      title={p.title}
                      score={p.score}
                      scoreText={scoreText}
                      primary={t.primary}
                      secondary={t.secondary}
                      tooltip={tooltip}
                    />
                  )
                })}
              </div>
            </div>
          </div>

	          <div className="lg:border-l lg:border-outline/8 lg:pl-6">
	            <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Liquidity vs Stress</p>
                  <p className="mt-1 text-sm text-muted-foreground">Trailing daily state (last {mapPoints.length} points)</p>
                </div>
                <Badge variant="outline" className="text-xs">
                  corr60 {nowcast.spx_tlt_corr60 == null ? '-' : formatMaybeNumber(nowcast.spx_tlt_corr60, 2)}
                </Badge>
              </div>
	              <div className="mt-3">
	                {mapPoints.length ? (
	                  <div className="w-full max-w-[420px] aspect-[420/240]">
	                    <RiskMapMini points={mapPoints} width={420} height={240} />
	                  </div>
	                ) : (
	                  <p className="text-sm text-muted-foreground">No map data available.</p>
	                )}
	              </div>
	              <div className="mt-2 text-xs text-muted-foreground">
	                Stress = mean(funding, credit, MOVE, SKEW). Liquidity axis uses rule-based ON RRP / TGA regime mapping.
              </div>
            </div>
          </div>
        </div>
    </ChartCard>
  )
}
