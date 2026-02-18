'use client'

import { MouseEvent, useState } from 'react'
import { ChartTooltip } from '@/components/charts/chart-tooltip'

export { formatNumberValue, formatPct } from '@/lib/format'

export function formatDate(s?: string) {
  if (!s) return ''
  try {
    return new Date(s).toLocaleDateString()
  } catch {
    return s
  }
}

export function prettyRegime(label?: string) {
  switch (label) {
    case 'momentum_led':
      return 'Momentum‑Led'
    case 'value_led':
      return 'Value‑Led'
    case 'transition':
      return 'Transition'
    case 'stress':
      return 'Stress'
    default:
      return '-'
  }
}

export function regimeColor(label?: string) {
  switch (label) {
    case 'momentum_led':
      return 'text-status-success'
    case 'value_led':
      return 'text-status-info'
    case 'stress':
      return 'text-status-danger'
    default:
      return 'text-foreground'
  }
}

export function prettyMarketStructureLabel(label?: string) {
  switch (label) {
    case 'CalmUptrend':
      return 'Calm Uptrend'
    case 'FragileUptrend':
      return 'Fragile Uptrend'
    case 'Choppy':
      return 'Choppy / Range'
    case 'Risk-Off':
      return 'Risk-Off'
    default:
      return 'Neutral'
  }
}

export function marketStructureLabelColor(label?: string) {
  switch (label) {
    case 'CalmUptrend':
      return 'text-status-success'
    case 'FragileUptrend':
      return 'text-status-warning-foreground'
    case 'Choppy':
      return 'text-status-info'
    case 'Risk-Off':
      return 'text-status-danger'
    default:
      return 'text-foreground'
  }
}

export function FRIDial({ value, width = 140, height = 80 }: { value?: number; width?: number; height?: number }) {
  const maxAbs = 16
  const neutralAbs = 0.5
  const vRaw = Number.isFinite(value) ? Number(value) : NaN
  const v = Number.isFinite(vRaw) ? Math.max(-maxAbs, Math.min(maxAbs, vRaw)) : 0
  const frac = (v + maxAbs) / (2 * maxAbs)
  const neutralLoFrac = (maxAbs - neutralAbs) / (2 * maxAbs)
  const neutralHiFrac = (maxAbs + neutralAbs) / (2 * maxAbs)

  const pointerColor =
    v >= neutralAbs
      ? 'hsl(var(--status-success))'
      : v <= -neutralAbs
        ? 'hsl(var(--status-danger))'
        : 'hsl(var(--status-warning))'
  const angle = frac * Math.PI
  const cx = width / 2
  const cy = height
  const r = Math.min(width * 0.45, height * 0.95)
  const x = cx + r * Math.cos(Math.PI - angle)
  const y = cy - r * Math.sin(Math.PI - angle)

  const polar = (t: number) => {
    const a = t * Math.PI
    return {
      x: cx + r * Math.cos(Math.PI - a),
      y: cy - r * Math.sin(Math.PI - a),
    }
  }
  const arc = (t0: number, t1: number) => {
    const p0 = polar(t0)
    const p1 = polar(t1)
    return `M ${p0.x},${p0.y} A ${r},${r} 0 0 1 ${p1.x},${p1.y}`
  }

  const tick = (t: number) => {
    const a = t * Math.PI
    const ix = cx + (r - 6) * Math.cos(Math.PI - a)
    const iy = cy - (r - 6) * Math.sin(Math.PI - a)
    const ox = cx + (r + 2) * Math.cos(Math.PI - a)
    const oy = cy - (r + 2) * Math.sin(Math.PI - a)
    return <line key={t} x1={ix} y1={iy} x2={ox} y2={oy} stroke="hsl(var(--outline) / 0.18)" strokeWidth={1} />
  }

  const display = Number.isFinite(vRaw) ? vRaw.toFixed(2) : '-'
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label="FRI dial"
      className="text-foreground"
    >
      <title>Dial: Left = Value‑led (negative FRI), Right = Momentum‑led (positive FRI)</title>
      <path d={arc(0, 1)} fill="none" stroke="hsl(var(--outline) / 0.10)" strokeWidth={8} />
      <path d={arc(0, neutralLoFrac)} fill="none" stroke="hsl(var(--status-danger))" strokeWidth={8} />
      <path d={arc(neutralLoFrac, neutralHiFrac)} fill="none" stroke="hsl(var(--muted-foreground) / 0.55)" strokeWidth={8} />
      <path d={arc(neutralHiFrac, 1)} fill="none" stroke="hsl(var(--status-success))" strokeWidth={8} />
      {[0, 0.25, 0.5, 0.75, 1].map(tick)}
      <circle cx={cx} cy={cy} r={3} fill={pointerColor} />
      <line x1={cx} y1={cy} x2={x} y2={y} stroke={pointerColor} strokeWidth={3} />
      <text x={cx} y={cy - 14} textAnchor="middle" fontSize="16" fontWeight="600" fill="currentColor">
        {display}
      </text>
      <text x={cx} y={cy - 2} textAnchor="middle" fontSize="10" fill="currentColor" opacity={0.7}>
        FRI z
      </text>
    </svg>
  )
}

export function RegimeIndexGauge({
  value,
  width = 320,
  height = 80,
}: {
  value?: number
  width?: number
  height?: number
}) {
  const vRaw = Number.isFinite(value) ? Number(value) : NaN
  const v = Number.isFinite(vRaw) ? Math.max(0, Math.min(100, vRaw)) : 50
  const cx = width / 2
  const cy = height
  const r = Math.min(width * 0.45, height * 0.95)
  const frac = v / 100
  const angle = frac * Math.PI
  const x = cx + r * Math.cos(Math.PI - angle)
  const y = cy - r * Math.sin(Math.PI - angle)

  const pointerColor =
    v >= 55 ? 'hsl(var(--status-success))' : v <= 45 ? 'hsl(var(--status-danger))' : 'hsl(var(--status-warning))'

  const polar = (t: number) => {
    const a = t * Math.PI
    return {
      x: cx + r * Math.cos(Math.PI - a),
      y: cy - r * Math.sin(Math.PI - a),
    }
  }
  const arc = (t0: number, t1: number) => {
    const p0 = polar(t0)
    const p1 = polar(t1)
    return `M ${p0.x},${p0.y} A ${r},${r} 0 0 1 ${p1.x},${p1.y}`
  }

  const tick = (t: number) => {
    const a = t * Math.PI
    const ix = cx + (r - 6) * Math.cos(Math.PI - a)
    const iy = cy - (r - 6) * Math.sin(Math.PI - a)
    const ox = cx + (r + 2) * Math.cos(Math.PI - a)
    const oy = cy - (r + 2) * Math.sin(Math.PI - a)
    return <line key={t} x1={ix} y1={iy} x2={ox} y2={oy} stroke="hsl(var(--outline) / 0.18)" strokeWidth={1} />
  }

  const display = Number.isFinite(vRaw) ? Math.round(v).toString() : '-'

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label="Risk dial gauge"
      className="text-foreground"
    >
      <title>Risk dial (Regime Index): left = risk-off, right = risk-on</title>

      <path d={arc(0, 1)} fill="none" stroke="hsl(var(--outline) / 0.10)" strokeWidth={8} />
      <path d={arc(0, 0.45)} fill="none" stroke="hsl(var(--status-danger))" strokeWidth={8} />
      <path d={arc(0.45, 0.55)} fill="none" stroke="hsl(var(--muted-foreground) / 0.55)" strokeWidth={8} />
      <path d={arc(0.55, 1)} fill="none" stroke="hsl(var(--status-success))" strokeWidth={8} />

      {[0, 0.25, 0.5, 0.75, 1].map(tick)}
      <circle cx={cx} cy={cy} r={3} fill={pointerColor} />
      <line x1={cx} y1={cy} x2={x} y2={y} stroke={pointerColor} strokeWidth={3} />

      <text x={cx} y={cy - 14} textAnchor="middle" fontSize="18" fontWeight="600" fill="currentColor">
        {display}
      </text>
      <text x={cx} y={cy - 2} textAnchor="middle" fontSize="10" fill="currentColor" opacity={0.7}>
        0–100
      </text>
    </svg>
  )
}

export function SparklineMini({
  data,
  width = 220,
  height = 64,
  domainY,
  color = 'hsl(var(--status-info))',
  format,
  label,
  neutralBand,
}: {
  data: { x: string; y: number }[]
  width?: number
  height?: number
  domainY?: [number, number]
  color?: string
  format?: (y: number) => string
  label?: string
  neutralBand?: [number, number]
}) {
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null)
  const innerW = width
  const innerH = height - 4
  const ys = data.map((d) => d.y).filter((v) => Number.isFinite(v))
  if (!ys.length) return <svg width={width} height={height} />
  const minY = domainY ? domainY[0] : Math.min(...ys)
  const maxY = domainY ? domainY[1] : Math.max(...ys)
  const spanY = maxY - minY || 1
  const n = data.length
  const dx = n > 1 ? innerW / (n - 1) : innerW
  const toY = (v: number) => {
    const norm = (v - minY) / spanY
    const clamped = Math.max(0, Math.min(1, norm))
    return innerH - clamped * innerH
  }
  let path = ''
  data.forEach((d, i) => {
    const cmd = i === 0 ? 'M' : 'L'
    const x = i * dx
    const y = toY(d.y)
    path += `${cmd}${x.toFixed(1)},${y.toFixed(1)} `
  })
  const onMove = (evt: MouseEvent<SVGSVGElement>) => {
    const rect = (evt.target as SVGElement).closest('svg')?.getBoundingClientRect()
    if (!rect) return
    const mx = evt.clientX - rect.left
    const i = Math.max(0, Math.min(n - 1, Math.round(mx / dx)))
    setHover({ i, x: i * dx, y: toY(data[i].y) })
  }
  const onLeave = () => setHover(null)
  const last = data[data.length - 1]?.y
  const zeroY = toY(0)
  const fmt = (y: number) => (format ? format(y) : Number.isFinite(y) ? y.toFixed(2) : '-')
  const fmtDelta = (curr: number, prev: number | null) => {
    if (prev == null || !Number.isFinite(prev)) return '-'
    const delta = curr - prev
    const sign = delta > 0 ? '+' : delta < 0 ? '-' : ''
    const abs = Math.abs(delta)
    return `${sign}${format ? fmt(abs) : abs.toFixed(2)}`
  }
  const hoverLines = hover
    ? [
        { label: 'Date', value: new Date(data[hover.i].x).toLocaleDateString() },
        { label: 'Value', value: fmt(data[hover.i].y) },
        {
          label: 'Δ',
          value: fmtDelta(data[hover.i].y, hover.i > 0 ? data[hover.i - 1]?.y : null),
        },
      ]
    : []

  return (
    <div className="relative">
      {hover && (
        <div className="pointer-events-none absolute -top-2 right-0">
          <ChartTooltip
            title={label}
            lines={hoverLines}
            className="shadow-md"
          />
        </div>
      )}
      <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={onLeave}>
        {neutralBand && (
          <rect
            x={0}
            y={Math.min(toY(neutralBand[0]), toY(neutralBand[1]))}
            width={width}
            height={Math.abs(toY(neutralBand[1]) - toY(neutralBand[0]))}
            fill="hsl(var(--outline) / 0.06)"
          />
        )}
        {domainY && domainY[0] < 0 && domainY[1] > 0 && (
          <line x1={0} y1={zeroY} x2={width} y2={zeroY} stroke="hsl(var(--outline) / 0.10)" strokeDasharray="4 4" />
        )}
        <path d={path} fill="none" stroke={color} strokeWidth={2} />
        <circle cx={innerW} cy={toY(last)} r={2.5} fill={color} />
        {hover && (
          <>
            <line x1={hover.x} y1={0} x2={hover.x} y2={height} stroke="hsl(var(--outline) / 0.12)" strokeDasharray="3 3" />
            <circle cx={hover.x} cy={hover.y} r={3} fill={color} stroke="hsl(var(--background))" strokeWidth={1} />
          </>
        )}
      </svg>
    </div>
  )
}
