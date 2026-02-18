export type XYPoint = { x: string; y: number }

export const CYCLICAL_ETFS = new Set(['XLY', 'XLI', 'XLF', 'XLK', 'XLE', 'XLB', 'XLC'])
export const DEFENSIVE_ETFS = new Set(['XLP', 'XLV', 'XLU', 'XLRE'])

export function isEmptyResponse(x: unknown): x is { status: 'empty' } {
  if (!x || typeof x !== 'object') return false
  if (!('status' in x)) return false
  return (x as { status?: unknown }).status === 'empty'
}

export function formatSigned(value?: number | null, digits = 2, suffix = '') {
  if (value == null || !Number.isFinite(value)) return '-'
  const v = Number(value)
  const sign = v > 0 ? '+' : v < 0 ? '−' : ''
  return `${sign}${Math.abs(v).toFixed(digits)}${suffix}`
}

export function formatMillionsToBillionsSigned(valueMn?: number | null, digits = 1) {
  if (valueMn == null || !Number.isFinite(valueMn)) return '-'
  const bil = Number(valueMn) / 1_000
  return formatSigned(bil, digits, 'B')
}

export function mean(values: number[]) {
  if (!values.length) return 0
  return values.reduce((acc, v) => acc + v, 0) / values.length
}

export function stdSample(values: number[]) {
  if (values.length < 2) return 0
  const m = mean(values)
  const varSum = values.reduce((acc, v) => acc + (v - m) ** 2, 0)
  return Math.sqrt(varSum / (values.length - 1))
}

export function lastDelta(values: number[], lookback = 1): number | null {
  if (!Number.isFinite(lookback) || lookback < 1) return null
  if (values.length <= lookback) return null
  const latest = values[values.length - 1]
  const prev = values[values.length - 1 - lookback]
  if (!Number.isFinite(latest) || !Number.isFinite(prev)) return null
  return latest - prev
}

export function buildCycDefAppetiteSeries(
  rows: Array<{ date: string; sector_etf?: string | null; avg_score: number | null }>
): XYPoint[] {
  const byDate = new Map<string, Array<{ sector_etf?: string | null; avg_score: number | null }>>()
  for (const r of rows) {
    const d = r.date
    if (!d) continue
    if (!byDate.has(d)) byDate.set(d, [])
    byDate.get(d)!.push({ sector_etf: r.sector_etf, avg_score: r.avg_score })
  }

  const dates = Array.from(byDate.keys()).sort()
  const pts: XYPoint[] = []
  for (const d of dates) {
    const items = byDate.get(d) || []
    const cyc: number[] = []
    const def: number[] = []
    for (const it of items) {
      const etf = (it.sector_etf || '').toUpperCase().trim()
      const score = it.avg_score
      if (score == null || !Number.isFinite(score)) continue
      if (CYCLICAL_ETFS.has(etf)) cyc.push(Number(score))
      if (DEFENSIVE_ETFS.has(etf)) def.push(Number(score))
    }
    if (!cyc.length || !def.length) continue
    pts.push({ x: d, y: mean(cyc) - mean(def) })
  }
  return pts
}
