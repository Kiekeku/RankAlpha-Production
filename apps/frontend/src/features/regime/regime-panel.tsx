'use client'

import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { ChartHeader } from '@/components/charts/chart-header'
import { ChartSkeleton } from '@/components/charts/chart-skeleton'
import { InfoTooltip } from '@/components/info_tooltip_button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { TooltipCopy, TooltipCopyButton } from '@/components/tooltip_copy'
import { GlossaryTerm } from '@/components/glossary/GlossaryTerm'
import { isEmptyResponse } from '@/lib/nowcast-utils'
import { cn } from '@/lib/utils'
import { formatEasternDate } from '@/lib/date'
import {
  useBreadthFlow,
  useMarketStructureLatest,
  useMarketStructureSeries,
  useRankRegimeHistory,
  useRankRegimeLatest,
  useRegimeLatestIntensity,
  useRegimeLatestRules,
  useRegimeRulesSeries,
  useRegimeSeries,
} from './hooks'
import {
  FRIDial,
  SparklineMini,
  formatNumberValue,
  formatPct,
  marketStructureLabelColor,
  prettyMarketStructureLabel,
  prettyRegime,
  regimeColor,
} from './regime-shared'

const WINDOW_OPTIONS = [90, 180, 252] as const

const WINDOW_TIMEFRAMES = WINDOW_OPTIONS.map((w) => ({ key: `${w}d`, label: `${w}d` }))

function formatAsOf(value?: string | null) {
  return value ? formatEasternDate(value) : null
}

function toneForRulesRegimeLabel(label?: string): BadgeProps['variant'] {
  if (!label) return 'info'
  if (label === 'Risk-Off') return 'danger'
  if (label === 'Trend') return 'success'
  if (label === 'Chop') return 'warning'
  return 'info'
}

function toneForIntensityRegimeLabel(label?: string): BadgeProps['variant'] {
  if (!label) return 'info'
  if (label === 'Risk-Off') return 'danger'
  if (label === 'Risk-On') return 'success'
  return 'info'
}

export type RegimePanelProps = {
  initialMode?: 'rules' | 'intensity'
  onModeChange?: (mode: 'rules' | 'intensity') => void
}

export function RegimePanel({ initialMode = 'rules', onModeChange }: RegimePanelProps) {
  const [styleWindow, setStyleWindow] = useState<(typeof WINDOW_OPTIONS)[number]>(180)
  const [structureWindow, setStructureWindow] = useState<(typeof WINDOW_OPTIONS)[number]>(180)
  const [mode, setMode] = useState<'rules' | 'intensity'>(initialMode)

  useEffect(() => {
    setMode(initialMode)
  }, [initialMode])

  const handleModeChange = (next: 'rules' | 'intensity') => {
    setMode(next)
    onModeChange?.(next)
  }

  const { data: rankRegimeLatest, isLoading: rankRegimeLatestLoading } = useRankRegimeLatest()
  const { data: rankRegimeHistory, isLoading: rankRegimeHistoryLoading } = useRankRegimeHistory(styleWindow)
  const { data: marketStructureLatest, isLoading: marketStructureLatestLoading } = useMarketStructureLatest()
  const { data: marketStructureSeries, isLoading: marketStructureSeriesLoading } = useMarketStructureSeries(structureWindow)
  const { data: regimeLatestIntensity, isLoading: regimeIntensityLoading } = useRegimeLatestIntensity()
  const { data: regimeLatestRules, isLoading: regimeRulesLoading } = useRegimeLatestRules()
  const { data: regimeSeries } = useRegimeSeries(180, mode === 'intensity')
  const { data: regimeRulesSeries } = useRegimeRulesSeries(180, mode === 'rules')
  const { data: breadthFlow } = useBreadthFlow(120)

  const intensityLatest = regimeLatestIntensity && !isEmptyResponse(regimeLatestIntensity) ? regimeLatestIntensity : null
  const rulesLatest = regimeLatestRules && !isEmptyResponse(regimeLatestRules) ? regimeLatestRules : null

  const regimeSeriesData = useMemo(() => {
    if (mode === 'rules') {
      return (regimeRulesSeries?.items ?? []).map((row) => ({ x: row.as_of_date, y: row.rs }))
    }
    return (regimeSeries?.items ?? []).map((row) => ({ x: row.as_of_date, y: row.regime_index }))
  }, [mode, regimeRulesSeries, regimeSeries])
  const regimeSeriesHasSignal = regimeSeries?.coverage?.has_signal ?? true
  const regimeCoverageWarning = intensityLatest?.coverage_warning || regimeSeries?.coverage?.warning || null
  const regimeSeriesDataForMode = mode === 'intensity' && !regimeSeriesHasSignal ? [] : regimeSeriesData

  const breadthSparkData = useMemo(
    () => (breadthFlow?.items ?? []).map((row) => ({ x: row.change_date, y: row.net_pct_us_signed })),
    [breadthFlow]
  )

  const styleHistory = rankRegimeHistory?.items ?? []
  const friSeries = styleHistory.map((row) => ({ x: row.as_of_date, y: row.fri_z ?? 0 }))
  const breadthSpreadSeries = styleHistory.map((row) => ({ x: row.as_of_date, y: row.breadth_spread ?? 0 }))
  const tenureSeries = styleHistory.map((row) => ({ x: row.as_of_date, y: row.tenure_m_median_days ?? 0 }))

  const marketStructureHistory = marketStructureSeries?.items ?? []
  const marketStructureMetricConfigs = [
    {
      key: 'trend',
      title: 'Trend (t-stat)',
      subtitle: 'EW index slope',
      description: 'Equally weighted index slope normalized as a t-statistic. Positive readings = clean uptrend.',
      rawDisplay: formatNumberValue(marketStructureLatest?.trend_raw, 2),
      zDisplay: formatNumberValue(marketStructureLatest?.trend_z, 2),
      series: marketStructureHistory.map((row) => ({ x: row.as_of_date, y: Number(row.trend_z ?? 0) })),
      domain: [-2, 2],
      color: '#6366f1',
    },
    {
      key: 'rv',
      title: 'RV20 (ann.)',
      subtitle: '20d realized vol',
      description: '20-day realized volatility annualized. Rising RV implies fatter tails and more stress.',
      rawDisplay: formatPct(marketStructureLatest?.rv20_ann),
      zDisplay: formatNumberValue(marketStructureLatest?.rv20_z, 2),
      series: marketStructureHistory.map((row) => ({ x: row.as_of_date, y: Number(row.rv20_z ?? 0) })),
      domain: [-2, 2],
      color: '#f97316',
    },
    {
      key: 'corr',
      title: 'Correlation',
      subtitle: 'PC1 variance share',
      description: 'Variance explained by the first principal component. High values = one-factor tape / low dispersion.',
      rawDisplay: formatPct(marketStructureLatest?.corr_pca1_share),
      zDisplay: formatNumberValue(marketStructureLatest?.corr_z, 2),
      series: marketStructureHistory.map((row) => ({ x: row.as_of_date, y: Number(row.corr_z ?? 0) })),
      domain: [-2, 2],
      color: '#14b8a6',
    },
    {
      key: 'disp',
      title: 'Dispersion',
      subtitle: 'Cross-sec MAD',
      description: 'Cross-sectional median absolute deviation. Higher dispersion = alpha-rich environment.',
      rawDisplay: formatPct(marketStructureLatest?.disp_cs_mad),
      zDisplay: formatNumberValue(marketStructureLatest?.disp_z, 2),
      series: marketStructureHistory.map((row) => ({ x: row.as_of_date, y: Number(row.disp_z ?? 0) })),
      domain: [-2, 2],
      color: '#f43f5e',
    },
  ]

  return (
    <div className="space-y-6">
      <Card className="border-outline/8">
        <CardHeader className="relative z-10 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <ChartHeader
          title="Style Rotation (Momentum ↔ Value)"
          description="FRI, breadth spreads, and tenure to track leadership shifts."
          tooltipKey="regime.styleRotation"
          tooltipLabel="Style rotation"
          updatedAt={formatAsOf(rankRegimeLatest?.as_of_date)}
            methodologyHref="/about/regime"
            timeframes={WINDOW_TIMEFRAMES}
            activeTimeframe={`${styleWindow}d`}
            onTimeframeChange={(next) => setStyleWindow(Number(next.replace('d', '')) as (typeof WINDOW_OPTIONS)[number])}
            timeframeLabel="Window"
            timeframeHelp="Lookback window for z-scores and leadership metrics."
          />
        </CardHeader>
        <CardContent className="relative z-10">
          {rankRegimeLatestLoading || rankRegimeHistoryLoading ? (
            <div className="space-y-3">
              <ChartSkeleton className="h-32" />
              <ChartSkeleton className="h-28" />
            </div>
          ) : rankRegimeLatest ? (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-muted-foreground">Current Regime</div>
                    <div className={cn('mt-1 text-2xl font-bold tracking-tight', regimeColor(rankRegimeLatest.regime_label))}>
                      {prettyRegime(rankRegimeLatest.regime_label)}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">Confidence: {formatPct(rankRegimeLatest.regime_confidence)}</div>                  
                  </div>
                  <FRIDial value={rankRegimeLatest.fri_z} width={140} height={80} />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-md border border-border/50 p-2">
                    <div className="text-[11px] uppercase text-muted-foreground">Momentum</div>
                    <div className="mt-1 text-sm font-semibold">{formatPct(rankRegimeLatest.momentum_breadth)}</div>
                  </div>
                  <div className="rounded-md border border-border/50 p-2">
                    <div className="text-[11px] uppercase text-muted-foreground">Value</div>
                    <div className="mt-1 text-sm font-semibold">{formatPct(rankRegimeLatest.value_breadth)}</div>
                  </div>
                  <div className="rounded-md border border-border/50 p-2">
                    <div className="text-[11px] uppercase text-muted-foreground">Spread</div>
                    <div className="mt-1 text-sm font-semibold">{formatPct(rankRegimeLatest.breadth_spread)}</div>
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground">
                      <GlossaryTerm term="FRI" label="Factor Rotation Index (FRI)" className="text-muted-foreground no-underline" />
                    </div>
                    <div className="mt-1 text-2xl font-semibold">{formatNumberValue(rankRegimeLatest.fri_z)}</div>
                  </div>
                  <SparklineMini
                    data={friSeries}
                    width={220}
                    height={64}
                    domainY={[-2.5, 2.5]}
                    color="hsl(var(--status-info))"
                    label="FRI"
                    neutralBand={[-0.5, 0.5]}
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">Positive → Momentum-led; Negative → Value-led</p>
              </div>

              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground">
                      <span>Breadth Spread (M − V)</span>
                      <TooltipCopyButton
                        tooltipKey="regime.breadthSpread"
                        iconSize="h-3.5 w-3.5"
                        buttonClassName="text-muted-foreground hover:text-foreground"
                      />
                    </div>
                    <div className="mt-1 text-2xl font-semibold">{formatPct(rankRegimeLatest.breadth_spread)}</div>
                  </div>
                  <SparklineMini
                    data={breadthSpreadSeries}
                    width={220}
                    height={64}
                    domainY={[-0.2, 0.2]}
                    color="hsl(var(--status-success))"
                    label="Spread"
                    format={(y) => formatPct(Number(y))}
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">Share of universe in top-decile Momentum minus Value.</p>
              </div>

              <div className="md:col-span-3 rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <div className="flex items-center justify-between flex-wrap gap-4">
                 <div>
                    <div className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground">
                      <span>
                        Momentum Tenure {typeof rankRegimeLatest.tenure_m_median_days === 'number'
                          ? `${Math.round(rankRegimeLatest.tenure_m_median_days)}d`
                          : '-'}{' '}
                        (median days in top decile)
                      </span>
                      <TooltipCopyButton
                        tooltipKey="regime.momentumTenure"
                        iconSize="h-3.5 w-3.5"
                        buttonClassName="text-muted-foreground hover:text-foreground"
                      />
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">Rising tenure with +FRI → steadier trend regimes.</p>
                 </div>
                  <SparklineMini
                    data={tenureSeries}
                    width={520}
                    height={58}
                    color="hsl(var(--status-model))"
                    label="Tenure"
                    format={(y) => `${Math.round(Number(y))}d`}
                  />
                </div>
               
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No style regime data available.</p>
          )}
        </CardContent>
      </Card>

      {regimeCoverageWarning ? (
        <div className="rounded-2xl border border-status-warning/30 bg-status-warning/10 px-4 py-3 text-sm text-status-warning-foreground">
          {regimeCoverageWarning}
        </div>
      ) : null}

      <RegimeOverviewCard
        mode={mode}
        onModeChange={handleModeChange}
        regimeLatestRules={rulesLatest ?? undefined}
        regimeLatestIntensity={intensityLatest ?? undefined}
        regimeSeriesData={regimeSeriesDataForMode}
        breadthData={breadthSparkData}
        loading={mode === 'rules' ? (regimeRulesLoading && !rulesLatest) : (regimeIntensityLoading && !intensityLatest)}
      />

      <Card className="border-outline/8">
        <CardHeader className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <ChartHeader
          title="Market Structure (CVD)"
          description="Correlation–volatility–dispersion snapshot with regime context."
          tooltipKey="regime.marketStructure"
          tooltipLabel="Market structure"
          updatedAt={formatAsOf(marketStructureLatest?.as_of_date)}
            methodologyHref="/about/regime"
            timeframes={WINDOW_TIMEFRAMES}
            activeTimeframe={`${structureWindow}d`}
            onTimeframeChange={(next) => setStructureWindow(Number(next.replace('d', '')) as (typeof WINDOW_OPTIONS)[number])}
            timeframeLabel="Window"
            timeframeHelp="Lookback window for structure z-scores and dispersion."
          />
        </CardHeader>
        <CardContent className="relative z-10 space-y-6">
          {marketStructureLatestLoading && marketStructureSeriesLoading ? (
            <ChartSkeleton className="h-44" />
          ) : marketStructureLatest ? (
            <>
              <div className="rounded-2xl border border-outline/10 bg-secondary/12 px-4 py-2">
                <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <span>Tape Classification</span>
                    <span className={marketStructureLabelColor(marketStructureLatest.label)}>
                      {prettyMarketStructureLabel(marketStructureLatest.label)}
                    </span>
                    <InfoTooltip
                      description="Sparkline shows % net entrants (flow breadth). Positive = more long signals firing than dropping."
                      label="Flow breadth"
                      iconSize="h-3 w-3"
                    />
                  </div>
                  <SparklineMini
                    data={breadthSparkData}
                    width={300}
                    height={60}
                    color="#fbbf24"
                    label="Flow Breadth"
                    format={(y) => formatPct(Number(y))}
                    domainY={[-0.2, 0.2]}
                  />
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {marketStructureMetricConfigs.map((metric) => (
                  <div key={metric.key} className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                    <div className="flex items-center gap-1 text-xs uppercase tracking-wide text-muted-foreground">
                      <span>{metric.title}</span>
                      {metric.description ? (
                        <InfoTooltip description={metric.description} label={metric.title} iconSize="h-3.5 w-3.5" />
                      ) : null}
                    </div>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span className="text-2xl font-semibold">{metric.rawDisplay}</span>
                      <span className="text-xs text-muted-foreground">z {metric.zDisplay}</span>
                    </div>
                    <p className="text-[11px] text-muted-foreground">{metric.subtitle}</p>
                    <div className="mt-3">
                      <SparklineMini
                        data={metric.series}
                        width={240}
                        height={64}
                        domainY={metric.domain as [number, number]}
                        color={metric.color}
                        label={metric.title}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Market structure data is not available yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function RegimeOverviewCard({
  mode,
  onModeChange,
  regimeLatestRules,
  regimeLatestIntensity,
  regimeSeriesData,
  breadthData,
  loading,
}: {
  mode: 'rules' | 'intensity'
  onModeChange: (mode: 'rules' | 'intensity') => void
  regimeLatestRules?: ReturnType<typeof useRegimeLatestRules>['data']
  regimeLatestIntensity?: ReturnType<typeof useRegimeLatestIntensity>['data']
  regimeSeriesData: { x: string; y: number }[]
  breadthData: { x: string; y: number }[]
  loading?: boolean
}) {
  const rulesAsOf = regimeLatestRules && !isEmptyResponse(regimeLatestRules) ? regimeLatestRules.as_of_date : null
  const intensityAsOf =
    regimeLatestIntensity && !isEmptyResponse(regimeLatestIntensity) ? regimeLatestIntensity.as_of_date : null

  const renderRules = () => {
    if (!regimeLatestRules || isEmptyResponse(regimeLatestRules)) {
      return <p className="text-sm text-muted-foreground">Flow-based regime data is unavailable.</p>
    }
    const tags = regimeLatestRules.tags || []
    return (
      <div className="space-y-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-muted-foreground">Regime</span>
            <TooltipCopy tooltipKey={regimeLatestRules.label === 'Chop' ? 'overview.regime.chop' : 'overview.regime'}>
              <span>
                <Badge variant={toneForRulesRegimeLabel(regimeLatestRules.label)}>
                  {regimeLatestRules.label}
                </Badge>
              </span>
            </TooltipCopy>

            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-muted-foreground underline decoration-dotted decoration-outline/30 underline-offset-2">
                  RS {formatNumberValue(regimeLatestRules.rs)}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-sm px-3 py-2 text-xs leading-relaxed">
                Regime Score - net flow composite used by the rules-based regime model.
              </TooltipContent>
            </Tooltip>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            {tags.length ? tags.map((tag) => (
              <span key={tag} className="rounded-full border border-border/50 px-3 py-1 text-muted-foreground">
                {tag}
              </span>
            )) : <span className="text-muted-foreground">No playbook tags.</span>}
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
          <RegimeStat
            label="TT / ROP"
            value={`${formatNumberValue(regimeLatestRules.tt)} / ${formatNumberValue(regimeLatestRules.rop)}`}
            description="Trend Thrust vs Risk-Off Pressure. Higher TT and lower ROP = healthy breakout regime."
          />
          <RegimeStat
            label="MRP / DT"
            value={`${formatNumberValue(regimeLatestRules.mrp)} / ${formatNumberValue(regimeLatestRules.dt)}`}
            description="Mean Reversion Pressure vs Downturn Trigger. Elevated DT warns that breakdowns dominate."
          />
          <RegimeStat
            label="PS / TB"
            value={`${formatNumberValue(regimeLatestRules.ps)} / ${formatNumberValue(regimeLatestRules.tb)}`}
            description="Positioning Skew vs Trend Break. Skew tracks crowding; TB flags key levels cracking."
          />
          <RegimeStat
            label="RS Smooth"
            value={formatNumberValue(regimeLatestRules.rs_smooth)}
            description="10-day smoothed Regime Score to dampen day-to-day noise."
          />
        </div>
      </div>
    )
  }

  const renderIntensity = () => {
    if (!regimeLatestIntensity || isEmptyResponse(regimeLatestIntensity)) {
      return <p className="text-sm text-muted-foreground">Breadth-intensity regime data is unavailable.</p>
    }
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl border border-outline/10 bg-secondary/12 p-4">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Label</p>
          <div className="mt-1 flex items-center gap-2">
            <TooltipCopy tooltipKey={regimeLatestIntensity.regime_label === 'Chop' ? 'overview.regime.chop' : 'overview.regime'}>
              <span>
                <Badge variant={toneForIntensityRegimeLabel(regimeLatestIntensity.regime_label)}>
                  {regimeLatestIntensity.regime_label}
                </Badge>
              </span>
            </TooltipCopy>
          </div>
        </div>
        <RegimeStat
          label="Risk Dial (0–100)"
          value={Number.isFinite(regimeLatestIntensity.regime_index) ? Math.round(regimeLatestIntensity.regime_index).toString() : '-'}
          description="Breadth × intensity composite scaled 0–100. Higher readings = risk-on bias."
        />
        <RegimeStat
          label="Risk-On Core"
          value={formatNumberValue(regimeLatestIntensity.risk_on_core)}
          description="Long-side core: momentum, squeeze, and quality styles firing."
        />
        <RegimeStat
          label="Risk-Off Core"
          value={formatNumberValue(regimeLatestIntensity.risk_off_core)}
          description="Short-side core: breakdown, defensive, and risk-off screens triggering."
        />
      </div>
    )
  }

  return (
    <Card className="border-outline/8">
      <CardHeader className="relative z-10 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <ChartHeader
          title="Market Styles Flow"
          description="Flow-based rules + breadth intensity composites."
          tooltipKey="regime.marketStylesFlow"
          tooltipLabel="Market styles flow"
          updatedAt={formatAsOf(mode === 'rules' ? rulesAsOf : intensityAsOf)}
          methodologyHref="/about/regime"
          actions={(
            <div className="inline-flex rounded-full border border-outline/10 bg-card p-1 text-xs">
              <button
                type="button"
                onClick={() => onModeChange('rules')}
                className={cn(
                  'rounded-full px-3 py-1 font-semibold',
                  mode === 'rules' ? 'bg-primary text-primary-foreground shadow' : 'text-muted-foreground hover:text-primary'
                )}
                aria-pressed={mode === 'rules'}
              >
                Flow rules
              </button>
              <button
                type="button"
                onClick={() => onModeChange('intensity')}
                className={cn(
                  'rounded-full px-3 py-1 font-semibold',
                  mode === 'intensity' ? 'bg-primary text-primary-foreground shadow' : 'text-muted-foreground hover:text-primary'
                )}
                aria-pressed={mode === 'intensity'}
              >
                Breadth intensity
              </button>
            </div>
          )}
        />
      </CardHeader>
      <CardContent className="relative z-10 space-y-6">
        {loading ? (
          <ChartSkeleton className="h-32" />
        ) : (
          <>
            {mode === 'rules' ? renderRules() : renderIntensity()}
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">
                      {mode === 'rules' ? 'RS momentum' : 'Regime index'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {mode === 'rules'
                        ? 'Net flow composite (RS) - Trend vs Risk-Off'
                        : '0–100 breadth/intensity dial'}
                    </p>
                  </div>
                  <SparklineMini
                    data={regimeSeriesData}
                    width={280}
                    height={64}
                    color={mode === 'rules' ? '#f472b6' : '#22d3ee'}
                    label={mode === 'rules' ? 'RS' : 'Index'}
                  />
                </div>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">Flow breadth</p>
                    <p className="text-xs text-muted-foreground">Net entrants (% of universe)</p>
                  </div>
                  <SparklineMini
                    data={breadthData}
                    width={280}
                    height={64}
                    color="#fbbf24"
                    label="Net breadth"
                    domainY={[-0.2, 0.2]}
                    format={(y) => formatPct(Number(y))}
                  />
                </div>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function RegimeStat({ label, value, description }: { label: string; value: string; description?: string }) {
  return (
    <div className="rounded-2xl border border-outline/10 bg-secondary/12 p-4">
      <div className="flex items-center gap-1 text-xs uppercase tracking-wide text-muted-foreground">
        <span>{label}</span>
        {description ? (
          <InfoTooltip
            label={label}
            description={description}
            iconSize="h-3.5 w-3.5"
            contentClassName="max-w-sm px-ds-3 py-ds-2 text-ds-xs leading-relaxed"
          />
        ) : null}
      </div>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  )
}
