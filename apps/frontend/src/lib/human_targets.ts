export type HumanTargetInput = {
  base_price_target?: number | null
  human_analyst_target_median_usd?: number | null
  human_analyst_target_mean_usd?: number | null
  human_analyst_target_low_usd?: number | null
  human_analyst_target_high_usd?: number | null
}

export const HUMAN_TARGET_INLINE_BAND_PCT = 0.1

function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') {
    const cleaned = value.replace(/[^0-9.+-]/g, '').trim()
    if (!cleaned) return null
    const n = Number(cleaned)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function pickHumanEstimate(input: HumanTargetInput): number | null {
  const median = toFiniteNumber(input.human_analyst_target_median_usd)
  if (median != null) return median
  const mean = toFiniteNumber(input.human_analyst_target_mean_usd)
  if (mean != null) return mean
  const low = toFiniteNumber(input.human_analyst_target_low_usd)
  const high = toFiniteNumber(input.human_analyst_target_high_usd)
  if (low != null && high != null) return (low + high) / 2
  if (low != null) return low
  if (high != null) return high
  return null
}

export function computeHumanTargetBucket(
  input: HumanTargetInput,
  inlineBandPct: number = HUMAN_TARGET_INLINE_BAND_PCT,
): string | null {
  const base = toFiniteNumber(input.base_price_target)
  if (base == null || base === 0) return null
  const human = pickHumanEstimate(input)
  if (human == null) return null
  const diff = (human - base) / base
  if (Math.abs(diff) <= inlineBandPct) return 'inline RA est'
  return diff > 0 ? 'above RA est' : 'below RA est'
}
