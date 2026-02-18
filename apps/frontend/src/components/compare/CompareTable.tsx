import { Fragment, type ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import Link from 'next/link'

import { Badge } from '@/components/ui/badge'
import { DataTable } from '@/components/ui/data-table'
import { ColumnHeaderTooltip } from '@/components/column-header-tooltip'
import { formatEasternDate } from '@/lib/date'
import { formatNumberValue } from '@/lib/format'
import { cn } from '@/lib/utils'
import { UI_TERMS, formatSetupHitsLabel, formatSetupTag } from '@/lib/ui_terms'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { rememberTickerOrigin } from '@/lib/ticker_nav'
import {
  deltaLabel,
  earliestDate,
  formatMarketCap,
  marketCapBucket,
  setupTotals,
  trendRegime,
  volRegime,
  formatSignedPercent,
  formatPercent,
  targetUpsidePct,
} from '@/components/compare/compare-utils'

type HighlightRule = 'higher' | 'lower' | 'none'

type RowMeta = {
  value: number | null
  baselineValue: number | null
  delta: string | null
  deltaValue: number | null
  deltaDirection: -1 | 0 | 1
  highlightClass: string
}

type RowDefinition = {
  key: string
  label: string
  value?: (sym: string) => number | null
  highlight?: HighlightRule
  showDelta?: boolean
  format?: (value: number) => string
  render?: (sym: string, meta: RowMeta) => ReactNode
}

type SectionDefinition = {
  key: string
  title: string
  rows: RowDefinition[]
}

type CompareTableProps = {
  symbols: string[]
  baseline: string | null
  showDeltas: boolean
  assetBySymbol: Record<string, any>
  technicalsBySymbol: Record<string, any>
  priceBySymbol: Record<string, number | null>
  priceDateBySymbol: Record<string, string | null>
  setupBySymbol: Record<string, any>
  setupLongBySymbol: Record<string, any>
  setupsLoading: boolean
  setupsLongLoading: boolean
  shortWindowDays: number
  longWindowDays: number
}

function isFiniteNumber(value?: number | null) {
  return value != null && Number.isFinite(Number(value))
}

function getHighlightClass(value: number | null, values: number[], rule: HighlightRule) {
  if (rule === 'none' || value == null) return ''
  if (values.length < 2) return ''
  const max = Math.max(...values)
  const min = Math.min(...values)
  if (max === min) return ''
  const best = rule === 'lower' ? min : max
  const worst = rule === 'lower' ? max : min
  if (value === best) return 'bg-status-success/10 text-status-success'
  if (value === worst) return 'bg-status-danger/10 text-status-danger'
  return ''
}

function getDeltaValue(value: number | null, baselineValue: number | null) {
  if (!isFiniteNumber(value) || !isFiniteNumber(baselineValue)) return null
  return Number(value) - Number(baselineValue)
}

function getDeltaDirection(deltaValue: number | null): -1 | 0 | 1 {
  if (deltaValue == null) return 0
  const rounded = Math.round(deltaValue)
  if (rounded === 0) return 0
  return rounded > 0 ? 1 : -1
}

function DeltaBadge({ delta, direction }: { delta: string | null; direction: -1 | 0 | 1 }) {
  if (!delta) return null
  const icon =
    direction === 0 ? (
      <Minus className="h-3 w-3" aria-hidden />
    ) : direction > 0 ? (
      <ArrowUpRight className="h-3 w-3" aria-hidden />
    ) : (
      <ArrowDownRight className="h-3 w-3" aria-hidden />
    )
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
      {icon}
      <span>{delta}</span>
    </span>
  )
}

function renderNumericCell({
  value,
  format,
  showDelta,
  showHighlightIcon = true,
  highlightClass,
  delta,
  deltaDirection,
}: {
  value: number | null
  format?: (value: number) => string
  showDelta: boolean
  showHighlightIcon?: boolean
  highlightClass: string
  delta: string | null
  deltaDirection: -1 | 0 | 1
}) {
  if (!isFiniteNumber(value)) {
    return <span className="text-xs text-muted-foreground">-</span>
  }
  const label = format ? format(Number(value)) : formatNumberValue(Number(value), 0)
  const highlightMeta = showHighlightIcon
    ? highlightClass.includes('text-status-success')
      ? { label: 'Best in row', icon: <ArrowUpRight className="h-3 w-3" aria-hidden /> }
      : highlightClass.includes('text-status-danger')
        ? { label: 'Lowest in row', icon: <ArrowDownRight className="h-3 w-3" aria-hidden /> }
        : null
    : null
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-xs font-semibold tabular-nums sm:px-1.5 sm:text-sm',
        highlightClass || 'text-foreground',
      )}
    >
      <span>{label}</span>
      {highlightMeta ? (
        <span
          className="inline-flex items-center text-[10px] text-muted-foreground"
          title={highlightMeta.label}
        >
          <span className="sr-only">{highlightMeta.label}</span>
          {highlightMeta.icon}
        </span>
      ) : null}
      {showDelta ? <DeltaBadge delta={delta} direction={deltaDirection} /> : null}
    </div>
  )
}

function renderAsOfCell(
  dateValue: string | null | undefined,
  baselineDate: string | null | undefined,
  missingLabel = '-',
) {
  if (!dateValue) {
    return <span className="text-xs text-muted-foreground">{missingLabel}</span>
  }
  const label = formatEasternDate(dateValue)
  const mismatched = Boolean(baselineDate && baselineDate !== dateValue)
  return (
    <span className={cn('inline-flex items-center gap-1 text-xs font-semibold', mismatched ? 'text-status-warning' : 'text-foreground')}>
      {label}
      {mismatched ? <span title="Different from baseline">!</span> : null}
      {mismatched ? <span className="sr-only">Different from baseline</span> : null}
    </span>
  )
}

function resolveAiAsOf(ai: any): string | null {
  const raw = ai?.analysis_date ?? ai?.as_of_date
  if (!raw) return null
  return String(raw)
}

export function CompareTable({
  symbols,
  baseline,
  showDeltas,
  assetBySymbol,
  technicalsBySymbol,
  priceBySymbol,
  priceDateBySymbol,
  setupBySymbol,
  setupLongBySymbol,
  setupsLoading,
  setupsLongLoading,
  shortWindowDays,
  longWindowDays,
}: CompareTableProps) {
  const showRawData = SHOW_RAW_DATA
  const redactedCell = (
    <span className="inline-flex items-center rounded-md border border-outline/10 bg-card px-1 py-0.5 text-xs font-semibold text-muted-foreground blur-sm select-none">
      ****
    </span>
  )
  const baselineScoreDate = baseline ? assetBySymbol[baseline]?.current_grade?.date ?? null : null
  const baselinePriceDate = baseline ? priceDateBySymbol[baseline] ?? null : null
  const baselineTechnicalsDate = baseline ? technicalsBySymbol[baseline]?.as_of_date ?? null : null
  const baselineAiDate = baseline ? resolveAiAsOf(assetBySymbol[baseline]?.ai_analysis) : null
  const sections: SectionDefinition[] = [
    {
      key: 'price',
      title: 'Price / Trend',
      rows: [
        {
          key: 'scores-asof',
          label: 'Scores as of',
          render: (sym) => renderAsOfCell(assetBySymbol[sym]?.current_grade?.date, baselineScoreDate),
        },
        {
          key: 'price-asof',
          label: 'Price as of',
          render: (sym) =>
            renderAsOfCell(
              priceDateBySymbol[sym],
              baselinePriceDate,
              showRawData ? '-' : 'Hidden',
            ),
        },
        {
          key: 'technicals-asof',
          label: 'Technicals as of',
          render: (sym) => renderAsOfCell(technicalsBySymbol[sym]?.as_of_date, baselineTechnicalsDate),
        },
        {
          key: 'ai-asof',
          label: 'AI memo as of',
          render: (sym) => renderAsOfCell(resolveAiAsOf(assetBySymbol[sym]?.ai_analysis), baselineAiDate),
        },
        {
          key: 'sector',
          label: 'Sector / Industry',
          render: (sym) => {
            const asset = assetBySymbol[sym]
            const sector = asset?.sector ?? asset?.ai_analysis?.sector
            const industry = asset?.industry ?? asset?.ai_analysis?.industry
            if (!sector && !industry) return <span className="text-xs text-muted-foreground">-</span>
            return (
              <div className="text-xs text-muted-foreground">
                {sector || '-'}{industry ? ` · ${industry}` : ''}
              </div>
            )
          },
        },
        {
          key: 'liquidity',
          label: 'Liquidity proxy (MCap)',
          render: (sym) => {
            if (!showRawData) return redactedCell
            const asset = assetBySymbol[sym]
            const mcap = asset?.ai_analysis?.market_cap ?? asset?.market_cap ?? null
            if (!isFiniteNumber(mcap)) return <span className="text-xs text-muted-foreground">-</span>
            return (
              <div className="text-xs text-muted-foreground">
                {formatMarketCap(mcap)} · {marketCapBucket(mcap)}
              </div>
            )
          },
        },
        {
          key: 'trend',
          label: 'Trend regime',
          render: (sym) => {
            const momentum = assetBySymbol[sym]?.current_grade?.momentum_score ?? null
            return <div className="text-xs text-muted-foreground">{trendRegime(momentum)}</div>
          },
        },
        {
          key: 'target-price',
          label: 'Target price (12m)',
          value: showRawData ? (sym) => assetBySymbol[sym]?.target_price ?? null : () => null,
          highlight: 'none',
          showDelta: false,
          render: (_sym, meta) => {
            if (!showRawData) return redactedCell
            return renderNumericCell({
              value: meta.value,
              format: (v) => `$${formatNumberValue(v, 2)}`,
              showDelta: showDeltas && true,
              showHighlightIcon: false,
              highlightClass: meta.highlightClass,
              delta: meta.delta,
              deltaDirection: meta.deltaDirection,
            })
          },
        },
        {
          key: 'target-upside',
          label: 'Target vs price',
          value: (sym) => (showRawData ? targetUpsidePct(assetBySymbol[sym]?.target_price ?? null, priceBySymbol[sym] ?? null) : null),
          highlight: 'higher',
          showDelta: true,
          render: (sym, meta) => {
            if (!showRawData) return redactedCell
            const upside = targetUpsidePct(assetBySymbol[sym]?.target_price ?? null, priceBySymbol[sym] ?? null)
            if (upside == null) return <span className="text-xs text-muted-foreground">-</span>
            const delta = showDeltas && meta.delta ? `${meta.delta}%` : null
            return (
              <div className={cn('inline-flex items-center rounded-md px-1 py-0.5 text-xs font-semibold tabular-nums sm:px-1.5', meta.highlightClass || 'text-foreground')}>
                {formatSignedPercent(upside, 1)}
                {showDeltas ? <DeltaBadge delta={delta} direction={meta.deltaDirection} /> : null}
              </div>
            )
          },
        },
      ],
    },
    {
      key: 'fundamentals',
      title: showRawData ? 'Fundamentals' : 'Fundamentals (Hidden)',
      rows: [
        {
          key: 'projltgrowthrate',
          label: 'LT growth (5y est.)',
          value: showRawData ? (sym) => assetBySymbol[sym]?.projected_lt_growth_rate ?? null : () => null,
          highlight: 'higher',
          showDelta: false,
          render: (sym, meta) => {
            if (!showRawData) return redactedCell
            const value = assetBySymbol[sym]?.projected_lt_growth_rate ?? null
            if (value == null || !Number.isFinite(Number(value))) return <span className="text-xs text-muted-foreground">-</span>
            return (
              <div className={cn('inline-flex items-center rounded-md px-1 py-0.5 text-xs font-semibold tabular-nums sm:px-1.5', meta.highlightClass || 'text-foreground')}>
                {formatPercent(Number(value), 1)}
              </div>
            )
          },
        },
      ],
    },
    {
      key: 'factors',
      title: 'Factors',
      rows: [
        {
          key: 'grade',
          label: UI_TERMS.grade,
          render: (sym) => {
            const grade = assetBySymbol[sym]?.current_grade?.overall_grade
            return grade ? (
              <Badge variant="secondary" className="text-[11px] font-semibold">
                {grade}
              </Badge>
            ) : (
              <span className="text-xs text-muted-foreground">-</span>
            )
          },
        },
        {
          key: 'momentum',
          label: 'Momentum',
          value: (sym) => assetBySymbol[sym]?.current_grade?.momentum_score ?? null,
          highlight: 'higher',
          showDelta: true,
          format: (v) => formatNumberValue(v, 0),
        },
        {
          key: 'value',
          label: 'Value',
          value: (sym) => assetBySymbol[sym]?.current_grade?.value_score ?? null,
          highlight: 'higher',
          showDelta: true,
          format: (v) => formatNumberValue(v, 0),
        },
        {
          key: 'sentiment',
          label: 'Sentiment',
          value: (sym) => assetBySymbol[sym]?.current_grade?.sentiment_score ?? null,
          highlight: 'higher',
          showDelta: true,
          format: (v) => formatNumberValue(v, 0),
          render: (_sym, meta) => {
            if (!isFiniteNumber(meta.value)) {
              return <span className="text-xs text-muted-foreground">Sentiment unavailable: insufficient coverage</span>
            }
            return renderNumericCell({
              value: meta.value,
              format: (v) => formatNumberValue(v, 0),
              showDelta: showDeltas,
              highlightClass: meta.highlightClass,
              delta: meta.delta,
              deltaDirection: meta.deltaDirection,
            })
          },
        },
      ],
    },
    {
      key: 'setups',
      title: 'Setups',
      rows: [
        {
          key: 'setups-short',
          label: formatSetupHitsLabel(shortWindowDays),
          value: (sym) => setupTotals(setupBySymbol[sym]).total,
          highlight: 'higher',
          showDelta: true,
          render: (sym, meta) => {
            if (setupsLoading) return <span className="text-xs text-muted-foreground">Loading…</span>
            const setup = setupBySymbol[sym]
            const totals = setupTotals(setup)
            if (!totals.total) return <span className="text-xs text-muted-foreground">-</span>
            const topBullish = Array.isArray(setup?.bullish) ? setup.bullish.slice(0, 2) : []
            const topBearish = Array.isArray(setup?.bearish) ? setup.bearish.slice(0, 2) : []
            const labels = [
              ...topBullish.map((c: any) => formatSetupTag(c.label, c.streak_days)).filter(Boolean),
              ...topBearish.map((c: any) => formatSetupTag(c.label, c.streak_days)).filter(Boolean),
            ]
            return (
              <div className="space-y-1">
                <div
                  className={cn(
                    'inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-xs font-semibold sm:px-1.5',
                    meta.highlightClass || 'text-foreground',
                  )}
                >
                  <span className="tabular-nums">{totals.total} hits</span>
                  <DeltaBadge delta={meta.delta} direction={meta.deltaDirection} />
                </div>
                <div className="text-xs text-muted-foreground">Bull {topBullish.length} · Bear {topBearish.length}</div>
                <div className="text-xs text-foreground">{labels.join(', ') || '-'}</div>
              </div>
            )
          },
        },
        {
          key: 'setups-long',
          label: formatSetupHitsLabel(longWindowDays),
          value: (sym) => setupTotals(setupLongBySymbol[sym]).total,
          highlight: 'higher',
          showDelta: true,
          render: (sym, meta) => {
            if (setupsLongLoading) return <span className="text-xs text-muted-foreground">Loading…</span>
            const totals = setupTotals(setupLongBySymbol[sym])
            if (!totals.total) return <span className="text-xs text-muted-foreground">-</span>
            return (
              <div className="space-y-1">
                <div
                  className={cn(
                    'inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-xs font-semibold sm:px-1.5',
                    meta.highlightClass || 'text-foreground',
                  )}
                >
                  <span className="tabular-nums">{totals.total} hits</span>
                  <DeltaBadge delta={meta.delta} direction={meta.deltaDirection} />
                </div>
                <div className="text-xs text-muted-foreground">
                  Bull {totals.bull} · Bear {totals.bear}
                </div>
              </div>
            )
          },
        },
      ],
    },
    {
      key: 'ai',
      title: 'AI Targets',
      rows: [
        {
          key: 'ai-base',
          label: UI_TERMS.aiTargetBase,
          value: (sym) => assetBySymbol[sym]?.ai_analysis?.scenarios?.base?.price ?? null,
          highlight: 'higher',
          showDelta: true,
          format: (v) => `$${formatNumberValue(v, 2)}`,
          render: (sym, meta) => {
            const scenarios = assetBySymbol[sym]?.ai_analysis?.scenarios
            const price = scenarios?.base?.price ?? null
            const prob = scenarios?.base?.probability_pct ?? null
            if (!isFiniteNumber(price)) return <span className="text-xs text-muted-foreground">-</span>
            return (
              <div className="space-y-1">
                <div
                  className={cn(
                    'inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-xs font-semibold tabular-nums sm:px-1.5',
                    meta.highlightClass || 'text-foreground',
                  )}
                >
                  <span>${formatNumberValue(price, 2)}</span>
                  <DeltaBadge delta={meta.delta} direction={meta.deltaDirection} />
                </div>
                <div className="text-xs text-muted-foreground">{prob != null ? `${formatNumberValue(prob, 0)}%` : '-'}</div>
              </div>
            )
          },
        },
        {
          key: 'ai-confidence',
          label: 'AI confidence / date',
          render: (sym) => {
            const confidence = assetBySymbol[sym]?.ai_analysis?.confidence ?? null
            const asOf = resolveAiAsOf(assetBySymbol[sym]?.ai_analysis)
            if (!confidence && !asOf) return <span className="text-xs text-muted-foreground">-</span>
            return (
              <div className="text-xs text-muted-foreground">
                {confidence ? `Confidence ${confidence}` : 'Confidence -'}
                {asOf ? ` · ${formatEasternDate(asOf)}` : ''}
              </div>
            )
          },
        },
        {
          key: 'catalyst',
          label: 'Next catalyst date',
          render: (sym) => {
            const ai = assetBySymbol[sym]?.ai_analysis
            const dates = [
              ...(ai?.events ?? []).map((e: any) => e?.expected_date),
              ...(ai?.catalysts?.shortTerm ?? []).map((c: any) => c?.expected_date),
              ...(ai?.catalysts?.longTerm ?? []).map((c: any) => c?.expected_date),
            ]
            const next = earliestDate(dates)
            return <span className="text-xs text-muted-foreground">{next ? formatEasternDate(next) : '-'}</span>
          },
        },
      ],
    },
    {
      key: 'risk',
      title: 'Risk',
      rows: [
        {
          key: 'vol',
          label: 'Volatility regime',
          render: (sym) => {
            const technicals = technicalsBySymbol[sym]
            const volZ20 = technicals?.vol_z20 ?? null
            const beta = assetBySymbol[sym]?.ai_analysis?.beta ?? assetBySymbol[sym]?.beta ?? null
            if (!isFiniteNumber(volZ20) && !isFiniteNumber(beta)) return <span className="text-xs text-muted-foreground">-</span>
            return <div className="text-xs text-muted-foreground">{volRegime(beta, volZ20)}</div>
          },
        },
        {
          key: 'beta',
          label: 'Beta (S&P 500)',
          value: showRawData ? (sym) => assetBySymbol[sym]?.ai_analysis?.beta ?? assetBySymbol[sym]?.beta ?? null : () => null,
          highlight: 'lower',
          showDelta: true,
          render: (_sym, meta) => {
            if (!showRawData) return redactedCell
            return renderNumericCell({
              value: meta.value,
              format: (v) => formatNumberValue(v, 2),
              showDelta: showDeltas && true,
              showHighlightIcon: false,
              highlightClass: meta.highlightClass,
              delta: meta.delta,
              deltaDirection: meta.deltaDirection,
            })
          },
        },
      ],
    },
  ]

  return (
    <DataTable className="data-table--sticky min-w-[680px] sm:min-w-[760px]">
      <thead>
        <tr className="text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <th className="sticky left-0 top-0 z-30 border-b border-outline/10 bg-card/95 px-2 py-2 backdrop-blur sm:px-3">
            <ColumnHeaderTooltip label="Metric" tooltipKey="table.metric" />
          </th>
          {symbols.map((sym) => {
            const asset = assetBySymbol[sym]
            const grade = asset?.current_grade?.overall_grade
            const isBaseline = baseline === sym
            return (
              <th
                key={sym}
                className={cn(
                  'sticky top-0 z-20 border-b border-outline/10 bg-card/95 px-2 py-2 align-bottom backdrop-blur sm:px-3',
                  isBaseline && 'bg-primary/5',
                )}
              >
                <div className="min-w-0 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-foreground">{sym}</span>
                    {grade ? (
                      <Badge variant="secondary" className="text-[11px] font-semibold">
                        {grade}
                      </Badge>
                    ) : null}
                    {isBaseline ? (
                      <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                        Baseline
                      </span>
                    ) : null}
                  </div>
                  <div className="max-w-[16rem] truncate text-[11px] font-medium normal-case text-muted-foreground">
                    {asset?.company_name || '-'}
                  </div>
                  <Link
                    href={`/ticker/${encodeURIComponent(sym)}`}
                    onClick={() => rememberTickerOrigin('compare')}
                    className="inline-flex items-center text-[11px] font-semibold text-primary hover:underline"
                  >
                    Open ticker
                  </Link>
                </div>
             </th>
            )
          })}
        </tr>
      </thead>
      <tbody>
        {sections.map((section) => (
          <Fragment key={section.key}>
            <tr className="border-t-2 border-outline/15">
              <td
                colSpan={symbols.length + 1}
                className="bg-secondary/10 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground sm:px-3"
              >
                {section.title}
              </td>
            </tr>
            {section.rows.map((row) => {
              const valueFn = row.value
              const baselineValue = baseline && valueFn ? valueFn(baseline) : null
              const values = valueFn
                ? symbols
                  .map((sym) => valueFn(sym))
                  .filter((v): v is number => isFiniteNumber(v))
                : []
              return (
                <tr key={row.key} className="border-t border-outline/10">
                  <td className="sticky left-0 z-20 bg-card/95 px-2 py-2 text-xs font-semibold text-muted-foreground backdrop-blur sm:px-3">
                    {row.label}
                  </td>
                  {symbols.map((sym) => {
                    const value = valueFn ? valueFn(sym) : null
                    const deltaValue = showDeltas && (row.showDelta ?? true) && valueFn ? getDeltaValue(value, baselineValue) : null
                    const delta = showDeltas && (row.showDelta ?? true) && valueFn ? deltaLabel(value, baselineValue) : null
                    const highlightClass = valueFn ? getHighlightClass(value, values, row.highlight ?? 'none') : ''
                    const deltaDirection = getDeltaDirection(deltaValue)
                    const meta: RowMeta = {
                      value,
                      baselineValue,
                      delta,
                      deltaValue,
                      deltaDirection,
                      highlightClass,
                    }
                    return (
                      <td key={`${row.key}-${sym}`} className={cn('px-2 py-2 align-top sm:px-3', baseline === sym && 'bg-primary/5')}>
                        {row.render
                          ? row.render(sym, meta)
                          : renderNumericCell({
                              value,
                              format: row.format,
                              showDelta: showDeltas && (row.showDelta ?? true),
                              showHighlightIcon: false,
                              highlightClass,
                              delta,
                              deltaDirection,
                            })}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </Fragment>
        ))}
      </tbody>
    </DataTable>
  )
}
