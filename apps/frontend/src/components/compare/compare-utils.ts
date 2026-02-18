export function formatMarketCap(value?: number | null) {
  if (value == null || !Number.isFinite(Number(value))) return '-'
  const v = Number(value)
  const abs = Math.abs(v)
  if (abs >= 1_000_000_000_000) return `$${(v / 1_000_000_000_000).toFixed(2)}T`
  if (abs >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`
  if (abs >= 1_000_000) return `$${Math.round(v / 1_000_000)}M`
  return `$${Math.round(v)}`
}

export function marketCapBucket(value?: number | null) {
  if (value == null || !Number.isFinite(Number(value))) return '-'
  const v = Number(value)
  if (v >= 200_000_000_000) return 'Mega'
  if (v >= 10_000_000_000) return 'Large'
  if (v >= 2_000_000_000) return 'Mid'
  if (v >= 300_000_000) return 'Small'
  return 'Micro'
}

export function trendRegime(momentum?: number | null) {
  if (momentum == null || !Number.isFinite(Number(momentum))) return '-'
  const v = Number(momentum)
  if (v >= 70) return 'Uptrend'
  if (v <= 30) return 'Downtrend'
  return 'Neutral'
}

export function volRegime(beta?: number | null, volZ20?: number | null) {
  if (volZ20 != null && Number.isFinite(Number(volZ20))) {
    const z = Number(volZ20)
    if (z >= 1) return `High (Z ${z.toFixed(2)})`
    if (z <= -1) return `Low (Z ${z.toFixed(2)})`
    return `Normal (Z ${z.toFixed(2)})`
  }
  if (beta == null || !Number.isFinite(Number(beta))) return '-'
  const v = Number(beta)
  if (v >= 1.2) return `High (β ${v.toFixed(2)})`
  if (v <= 0.8) return `Low (β ${v.toFixed(2)})`
  return `Normal (β ${v.toFixed(2)})`
}

export function setupTotals(summary: any) {
  if (!summary) return { total: 0, bull: 0, bear: 0, netBias: 'neutral', netStrength: '-' }
  const bull = (summary.bullish?.length ?? 0) + (summary.bullish_extra_count ?? 0)
  const bear = (summary.bearish?.length ?? 0) + (summary.bearish_extra_count ?? 0)
  return {
    total: bull + bear,
    bull,
    bear,
    netBias: summary.net_bias || 'neutral',
    netStrength: summary.net_strength || '-',
  }
}

export function earliestDate(dates: Array<string | undefined | null>) {
  const parsed = dates
    .map((d) => (d ? Date.parse(d) : NaN))
    .filter((n) => Number.isFinite(n))
  if (!parsed.length) return null
  const min = Math.min(...parsed)
  return new Date(min).toISOString().slice(0, 10)
}

export function deltaLabel(value?: number | null, baseline?: number | null) {
  if (baseline == null || value == null) return null
  const v = Number(value)
  const b = Number(baseline)
  if (!Number.isFinite(v) || !Number.isFinite(b)) return null
  const d = v - b
  if (Math.abs(d) < 1e-6) return '±0'
  const rounded = Math.round(d)
  if (rounded === 0) return '±0'
  const sign = rounded > 0 ? '+' : ''
  return `${sign}${rounded.toLocaleString()}`
}

export function formatSignedPercent(value?: number | null, digits = 1) {
  if (value === undefined || value === null || !Number.isFinite(value)) return '-'
  const n = Number(value)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}${Math.abs(n).toFixed(digits)}%`
}

export function formatPercent(value?: number | null, digits = 1) {
  if (value === undefined || value === null || !Number.isFinite(value)) return '-'
  return `${Number(value).toFixed(digits)}%`
}

export function targetUpsidePct(targetPrice?: number | null, currentPrice?: number | null) {
  if (targetPrice == null || currentPrice == null) return null
  const t = Number(targetPrice)
  const p = Number(currentPrice)
  if (!Number.isFinite(t) || !Number.isFinite(p) || p === 0) return null
  return (t / p - 1) * 100
}
