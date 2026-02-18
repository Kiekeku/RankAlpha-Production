'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type MouseEvent, type MouseEventHandler } from 'react'
import { buildPriceHistoryQuery } from '@/components/price-history-query'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { ChartTooltip } from '@/components/charts/chart-tooltip'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { REDACTION_LABEL } from '@/components/ui/redacted'
import { useHydrated } from '@/lib/use_hydrated'

type Scale = { minY: number; maxY: number; spanY: number }
type ChartPoint = { date: string; value: number; isLive?: boolean }
type ChartStats = { change: number; changePct: number; up: boolean; subtitle: string | null; first?: number; last?: number }
type AxisTick = { value: number; y: number }
type MonthTick = { x: number; label: string }
type SmaLine = { period: number; path: string; color: string; label: string; values: Array<number | null> }
type SmaConfig = { period: number; color: string; label: string }
type ChartContext = {
  normalized: boolean
  series: ChartPoint[]
  ys: number[]
  scale: Scale
  path: string
  dx: number
  subtitle: string | null
  stats: ChartStats
  innerWidth: number
  innerHeight: number
  margin: { left: number; right: number; top: number; bottom: number }
  yTicks: AxisTick[]
  xTicks: MonthTick[]
  yScale: (value: number) => number
  smaPaths: SmaLine[]
}

export const PRICE_HISTORY_SMA_CONFIGS: SmaConfig[] = [
  { period: 20, color: '#0ea5e9', label: '20 SMA' },
  { period: 50, color: '#6366f1', label: '50 SMA' },
  { period: 200, color: '#f97316', label: '200 SMA' },
]

function computeScale(ys: number[]): Scale {
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanY = maxY - minY || 1
  return { minY, maxY, spanY }
}

function toPath(xs: number[], ys: number[], width: number, height: number, scale?: Scale) {
  if (xs.length === 0) return ''
  const { minY, spanY } = scale ?? computeScale(ys)
  const n = xs.length
  const dx = n > 1 ? width / (n - 1) : 0
  const points = ys.map((y, i) => {
    const px = i * dx
    const norm = (y - minY) / spanY
    const clamped = Math.max(0, Math.min(1, norm))
    const py = height - clamped * height
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)},${py.toFixed(1)}`
  })
  return points.join(' ')
}

function computeSma(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null)
  if (!Number.isFinite(period) || period <= 0 || values.length < period) {
    return out
  }
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) {
      sum -= values[i - period]
    }
    if (i >= period - 1) {
      out[i] = sum / period
    }
  }
  return out
}

function buildPathFromValues(
  values: Array<number | null>,
  dx: number,
  yScale: (value: number) => number,
): string {
  if (!values.length || dx <= 0) return ''
  let path = ''
  let penDown = false
  values.forEach((value, idx) => {
    if (value == null) {
      penDown = false
      return
    }
    const y = yScale(value)
    if (!Number.isFinite(y)) {
      penDown = false
      return
    }
    const x = idx * dx
    const segment = `${penDown ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
    path += segment
    penDown = true
  })
  return path
}

export function PriceHistoryMini({
  symbol,
  days = 22,
  width = 160,
  height = 36,
  className,
  livePrice,
  liveAsOf,
  showLabel = true,
  showChange = true,
  onStats,
}: {
  symbol: string
  days?: number
  width?: number
  height?: number
  className?: string
  livePrice?: number | null
  liveAsOf?: string | null
  showLabel?: boolean
  showChange?: boolean
  onStats?: (stats: { change: number; changePct: number; up: boolean; subtitle: string | null; first?: number; last?: number; label: string }) => void
}) {
  const hydrated = useHydrated()
  const { queryKey, queryFn } = buildPriceHistoryQuery(symbol, days)
  const { data, isLoading, isError } = useQuery({
    queryKey,
    queryFn,
    enabled: hydrated && !!symbol,
    staleTime: 60_000,
  })

  // Hover state for tooltip (must be before any early returns so hooks order is stable)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const onStatsRef = useRef(onStats)
  useEffect(() => {
    onStatsRef.current = onStats
  }, [onStats])

  const label = useMemo(() => (days >= 240 ? 'Past Year' : days >= 60 ? 'Past 3 Months' : 'Past Month'), [days])

  const chartContext = useMemo<ChartContext | null>(() => {
    if (!data || isError) return null
    const items = Array.isArray(data.items) ? data.items : []
    if (!items.length && livePrice == null) return null

    const normalizeSeries = !SHOW_RAW_DATA && !data.normalized
    let didNormalize = false

    const margin = { left: 48, right: 6, top: 6, bottom: 20 }
    const innerWidth = Math.max(10, width - margin.left - margin.right)
    const innerHeight = Math.max(10, height - margin.top - margin.bottom)

    const liveValue = livePrice != null ? Number(livePrice) : null
    const preferAdjRaw = items.filter((d) => d.adj_close_px != null).length >= items.length / 2
    const useCloseField = liveValue != null ? true : !preferAdjRaw ? true : false
    let dailySeries: ChartPoint[] = [...items]
      .reverse()
      .map((d) => {
        const raw = (useCloseField ? d.close_px : d.adj_close_px) as number | undefined
        const val = raw !== undefined && raw !== null ? Number(raw) : NaN
        return { date: d.price_date, value: val }
      })
      .filter((d) => Number.isFinite(d.value))

    if (normalizeSeries) {
      const base = dailySeries.find((d) => Number.isFinite(d.value) && d.value !== 0)?.value ?? null
      if (base != null && Number.isFinite(base)) {
        dailySeries = dailySeries.map((d) => ({ ...d, value: (d.value / base) * 100 }))
        didNormalize = true
      }
    }

    const series: ChartPoint[] = dailySeries.slice(-days)

    const isNormalized = data.normalized || didNormalize

    if (liveValue != null && Number.isFinite(liveValue) && !isNormalized) {
      const lastPoint = series[series.length - 1]
      if (!lastPoint || Math.abs(lastPoint.value - liveValue) > 1e-6) {
        series.push({ date: liveAsOf || new Date().toISOString(), value: liveValue, isLive: true })
      } else if (lastPoint) {
        lastPoint.isLive = true
        lastPoint.value = liveValue
      }
    }

    if (!series.length) return null

    const perfWindow = dailySeries.slice(-days)
    const perfYs = perfWindow.map((d) => d.value)
    if (!perfYs.length) return null
    const first = perfYs[0]
    const last = perfYs[perfYs.length - 1]
    const change = last - first
    const changePct = first ? (change / first) * 100 : 0
    const up = change >= 0

    const ys = series.map((d) => d.value)
    const useLogScale = ys.every((v) => Number.isFinite(v) && v > 0)
    const scaledYs = useLogScale ? ys.map((v) => Math.log(v)) : ys
    const scale = computeScale(scaledYs)
    const path = toPath(series.map((_, i) => i), scaledYs, innerWidth, innerHeight, scale)
    const dx = series.length > 1 ? innerWidth / (series.length - 1) : innerWidth
    const latest = series[series.length - 1]
    const subtitle = latest?.isLive ? 'Live' : null
    const chartSubtitle = isNormalized && !subtitle ? 'Indexed (100=Start)' : subtitle

    const sortedYs = [...ys].sort((a, b) => a - b)
    const rawTicks = [sortedYs[0], sortedYs[sortedYs.length - 1]]
    const yScale = (value: number) => {
      if (!Number.isFinite(value)) return innerHeight / 2
      const raw = useLogScale ? Math.log(value) : value
      const norm = (raw - scale.minY) / scale.spanY
      const clamped = Math.max(0, Math.min(1, norm))
      return innerHeight - clamped * innerHeight
    }
    const yTicks: AxisTick[] = rawTicks
      .filter((value, idx, arr) => idx === 0 || Math.abs(value - arr[idx - 1]) > 1e-6)
      .map((value) => ({ value, y: yScale(value) }))

    const monthFormatter = new Intl.DateTimeFormat('en-US', { month: 'short' })
    const monthTickMap = new Map<string, { index: number; label: string }>()
    series.forEach((point, idx) => {
      const dt = new Date(point.date)
      if (Number.isNaN(dt.getTime())) return
      const key = `${dt.getFullYear()}-${dt.getMonth()}`
      if (!monthTickMap.has(key)) {
        monthTickMap.set(key, { index: idx, label: monthFormatter.format(dt) })
      }
    })
    if (!monthTickMap.size) {
      const dt = new Date(series[0].date)
      monthTickMap.set('0', { index: 0, label: Number.isNaN(dt.getTime()) ? '' : monthFormatter.format(dt) })
    }
    const monthTicks = Array.from(monthTickMap.values()).sort((a, b) => a.index - b.index)
    const firstDate = new Date(series[0].date)
    const firstLabel = Number.isNaN(firstDate.getTime()) ? '' : monthFormatter.format(firstDate)
    if (monthTicks.length) {
      if (monthTicks[0].label === firstLabel) {
        monthTicks[0] = { ...monthTicks[0], index: 0 }
      } else if (monthTicks[0].index !== 0) {
        monthTicks.unshift({ index: 0, label: firstLabel })
      }
    }
    const lastIdx = series.length - 1
    const lastDate = new Date(series[lastIdx].date)
    const lastLabel = Number.isNaN(lastDate.getTime()) ? '' : monthFormatter.format(lastDate)
    if (!monthTicks.length) {
      monthTicks.push({ index: lastIdx, label: lastLabel })
    } else {
      const lastTick = monthTicks[monthTicks.length - 1]
      if (lastTick.index === lastIdx) {
        monthTicks[monthTicks.length - 1] = { ...lastTick, label: lastTick.label || lastLabel }
      } else if (lastTick.label === lastLabel) {
        monthTicks.push({ index: lastIdx, label: '' })
      } else {
        monthTicks.push({ index: lastIdx, label: lastLabel })
      }
    }
    if (innerWidth <= 420 && monthTicks.length > 2) {
      monthTicks.forEach((tick, idx) => {
        const isLast = idx === monthTicks.length - 1
        if (isLast) {
          tick.label = ''
          return
        }
        if (idx > 0 && idx % 2 === 1) {
          tick.label = ''
        }
      })
    }

    const xTicks: MonthTick[] = monthTicks.map(({ index, label }) => {
      const t = series.length > 1 ? index / (series.length - 1) : 0
      return { x: t * innerWidth, label }
    })

    const closeValues = series.map((point) => point.value)
    const smaPaths: SmaLine[] = PRICE_HISTORY_SMA_CONFIGS.map(({ period, color, label }) => {
      const sma = computeSma(closeValues, period)
      const path = buildPathFromValues(sma, dx, yScale)
      if (!path.trim()) return null
      return { period, color, label, path, values: sma }
    }).filter((line): line is SmaLine => line !== null)

    return {
      normalized: isNormalized,
      series,
      ys,
      scale,
      path,
      dx,
      subtitle: chartSubtitle,
      stats: { change, changePct, up, first, last, subtitle: chartSubtitle },
      innerWidth,
      innerHeight,
      margin,
      yTicks,
      xTicks,
      yScale,
      smaPaths,
    }
  }, [data, days, height, isError, liveAsOf, livePrice, width])

  useEffect(() => {
    if (!chartContext || !onStatsRef.current) return
    const { change, changePct, up, first, last, subtitle } = chartContext.stats
    onStatsRef.current({ change, changePct, up, first, last, subtitle, label })
  }, [chartContext, label])

  if (!hydrated) return <Skeleton className="h-10 w-48" />
  if (isLoading) return <Skeleton className="h-10 w-48" />
  if (isError || !data) return null
  if (!chartContext) return null

  const { series, ys, path, dx, subtitle, stats, innerWidth, innerHeight, margin, yTicks, xTicks, yScale, smaPaths, normalized } = chartContext
  const { change, changePct, up } = stats
  const w = width
  const h = height
  const n = series.length
  const isNormalized = normalized
  const redactLabels = !SHOW_RAW_DATA

  const handleMove = (e: MouseEvent<SVGRectElement>) => {
    const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const x = e.clientX - rect.left
    const step = dx > 0 ? dx : innerWidth
    let i = step > 0 ? Math.round(x / step) : 0
    if (i < 0) i = 0
    if (i > n - 1) i = n - 1
    setHoverIdx(i)
  }
  const handleLeave: MouseEventHandler<SVGRectElement> = () => setHoverIdx(null)
  const fmtValue = (v: number) => {
    if (!Number.isFinite(v)) return '-'
    if (redactLabels) return '****'
    if (isNormalized) return v.toFixed(2)
    return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }

  const fmtDate = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }
  const fmtDelta = (curr: number, prev: number | null) => {
    if (prev == null || !Number.isFinite(prev)) return '-'
    if (redactLabels) return '****'
    const delta = curr - prev
    const sign = delta > 0 ? '+' : delta < 0 ? '-' : ''
    const abs = Math.abs(delta)
    const pct = prev !== 0 ? (delta / prev) * 100 : 0
    if (isNormalized) {
      return `${sign}${pct.toFixed(2)}%`
    }
    const pctLabel = prev !== 0 && Number.isFinite(pct) ? ` (${pct.toFixed(2)}%)` : ''
    return `${sign}${abs.toFixed(2)}${pctLabel}`
  }
  const fmtAxis = (v: number) => {
    if (redactLabels) return '****'
    if (isNormalized) return v.toFixed(1)
    return v.toLocaleString('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: Math.abs(v) < 10 ? 2 : 0,
      maximumFractionDigits: Math.abs(v) < 10 ? 2 : 1,
    })
  }

  const axisStroke = 'hsl(var(--border) / 0.28)'
  const gridStroke = 'hsl(var(--border) / 0.12)'
  const axisText = 'hsl(var(--muted-foreground))'
  const axisTextMuted = 'hsl(var(--muted-foreground) / 0.85)'
  const hoverStroke = 'hsl(var(--muted-foreground) / 0.55)'

  return (
    <div className={className}>
      {showLabel && (
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
          {label}
        </div>
      )}
      <div className="flex items-center gap-3">
        {showChange && (
          <div className="text-sm">
            <div className="leading-tight">
              <span
                className={cn(
                  up ? 'font-semibold tabular-nums text-status-success' : 'font-semibold tabular-nums text-status-danger',
                  redactLabels ? 'blur-sm select-none text-muted-foreground' : '',
                )}
              >
                {redactLabels
                  ? '****'
                  : isNormalized
                    ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(1)}%`
                    : `${change >= 0 ? '+' : ''}${change.toFixed(2)} (${changePct.toFixed(1)}%)`}
              </span>
            </div>
            {subtitle && <div className="text-xs text-muted-foreground">{subtitle}</div>}
            {redactLabels && <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{REDACTION_LABEL}</div>}
          </div>
        )}
        <div style={{ width: w, height: h }} className="relative">
          <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="overflow-visible">
            <g transform={`translate(${margin.left},${margin.top})`}>
              <line x1={0} y1={innerHeight} x2={innerWidth} y2={innerHeight} stroke={axisStroke} strokeWidth={0.75} />
              <line x1={0} y1={0} x2={0} y2={innerHeight} stroke={axisStroke} strokeWidth={0.75} />

              <g>
                {yTicks.map((tick, idx) => (
                  <g key={`yt-${idx}`}>
                    <line x1={0} x2={innerWidth} y1={tick.y} y2={tick.y} stroke={gridStroke} strokeWidth={0.75} strokeDasharray="4 4" />
                    <text
                      x={-8}
                      y={tick.y + 4}
                      textAnchor="end"
                      fontSize="10"
                      fill={axisText}
                      className={redactLabels ? 'blur-sm select-none' : undefined}
                    >
                      {fmtAxis(tick.value)}
                    </text>
                  </g>
                ))}
              </g>

              <g>
                {xTicks.map((tick, idx) => (
                  <g key={`xt-${idx}`} transform={`translate(${tick.x},0)`}>
                    <line x1={0} x2={0} y1={innerHeight} y2={innerHeight + 4} stroke={axisStroke} strokeWidth={0.75} />
                    <text
                      x={0}
                      y={innerHeight + 14}
                      textAnchor="middle"
                      fontSize="10"
                      fill={axisTextMuted}
                      className={redactLabels ? 'blur-sm select-none' : undefined}
                    >
                      {tick.label}
                    </text>
                  </g>
                ))}
              </g>

              {smaPaths.map((line) => (
                <path
                  key={`sma-${line.period}`}
                  d={line.path}
                  fill="none"
                  stroke={line.color}
                  strokeWidth={1.25}
                  strokeOpacity={0.95}
                />
              ))}

              <path d={path} fill="none" stroke={up ? 'hsl(var(--status-success))' : 'hsl(var(--status-danger))'} strokeWidth={2} />

              {hoverIdx != null && (
                <g>
                  <line x1={hoverIdx * dx} x2={hoverIdx * dx} y1={0} y2={innerHeight} stroke={hoverStroke} strokeDasharray="2,2" />
                  {(() => {
                    const yv = ys[hoverIdx]
                    const py = yScale(yv)
                    return <circle cx={hoverIdx * dx} cy={py} r={2.5} fill={up ? 'hsl(var(--status-success))' : 'hsl(var(--status-danger))'} />
                  })()}

                  {(() => {
                    const anchor = hoverIdx > n / 2 ? 'end' : 'start'
                    const priceAtIdx = ys[hoverIdx]
                    if (!Number.isFinite(priceAtIdx)) return null
                    const prevValue = hoverIdx > 0 ? ys[hoverIdx - 1] : null
                    const tooltipLines: Array<
                      | { type: 'text'; label?: string; value: string }
                      | { type: 'badge'; label: string; value: string; color?: string }
                    > = [
                      { type: 'text', label: 'Date', value: fmtDate(series[hoverIdx].date) },
                      { type: 'text', label: isNormalized ? 'Index' : 'Price', value: fmtValue(priceAtIdx) },
                      { type: 'text', label: 'Δ', value: fmtDelta(priceAtIdx, prevValue) },
                    ]
                    smaPaths.forEach((line) => {
                      const value = line.values[hoverIdx]
                      if (value == null || !Number.isFinite(value) || value === 0) return
                      const diffPct = ((priceAtIdx - value) / value) * 100
                      if (!Number.isFinite(diffPct)) return
                      const formatted = `${diffPct >= 0 ? '+' : ''}${Math.abs(diffPct) >= 100 ? diffPct.toFixed(0) : diffPct.toFixed(1)}%`
                      tooltipLines.push({
                        type: 'badge',
                        label: `SMA${line.period}`,
                        value: formatted,
                        color: line.color,
                      })
                    })
                    const baseX = hoverIdx * dx + (anchor === 'end' ? -6 : 6)
                    const baseY = Math.max(16, yScale(priceAtIdx) - 12)
                    const tooltipWidth = 190
                    const lineHeight = 16
                    const tooltipHeight = 20 + tooltipLines.length * lineHeight
                    const rawX = anchor === 'end' ? baseX - tooltipWidth : baseX
                    const clampedX = Math.max(0, Math.min(innerWidth - tooltipWidth, rawX))
                    const rawY = Math.min(innerHeight - tooltipHeight, Math.max(4, baseY - 8))
                    const clampedY = Math.max(0, rawY)
                    return (
                      <foreignObject
                        x={clampedX}
                        y={clampedY}
                        width={tooltipWidth}
                        height={tooltipHeight}
                        pointerEvents="none"
                      >
                        <ChartTooltip lines={tooltipLines} className={redactLabels ? 'blur-sm select-none' : undefined} />
                      </foreignObject>
                    )
                  })()}
                </g>
              )}

              <rect
                x={0}
                y={0}
                width={innerWidth}
                height={innerHeight}
                fill="transparent"
                onMouseMove={handleMove}
                onMouseLeave={handleLeave}
              />
            </g>
          </svg>
        </div>
      </div>
    </div>
  )
}
