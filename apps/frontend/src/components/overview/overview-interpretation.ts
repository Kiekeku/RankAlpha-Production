import type { NowcastLabel } from '@/lib/api'

export type OverviewImplicationInput = {
  nowcast_label?: NowcastLabel | null
  overall_risk_off_score?: number | null
  confidence?: number | null
  coverage?: number | null
  delta_1d?: number | null
  delta_5d?: number | null
  cross_asset_label?: NowcastLabel | null
  regime_rules_label?: string | null
  regime_rules_tags?: string[] | null
}

export type OverviewPlaybookBias = 'defensive' | 'momentum' | 'mean_reversion' | 'balanced'

export type OverviewPlaybook = {
  bias: OverviewPlaybookBias
  lowConviction: boolean
  riskRisingFast: boolean
  defensiveDrift: boolean
  speculativeMania: boolean
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function tagSet(tags: string[] | null | undefined) {
  const set = new Set<string>()
  for (const t of tags ?? []) {
    const s = (t ?? '').trim()
    if (s) set.add(s)
  }
  return set
}

function nowcastBand(nowcastLabel: NowcastLabel | null | undefined, score: number | null | undefined): NowcastLabel {
  if (nowcastLabel === 'risk_off' || nowcastLabel === 'risk_on' || nowcastLabel === 'neutral') return nowcastLabel
  if (isFiniteNumber(score)) {
    if (score >= 65) return 'risk_off'
    if (score <= 35) return 'risk_on'
  }
  return 'neutral'
}

function regimeTape(regimeLabel: string | null | undefined, tags: Set<string>) {
  const raw = (regimeLabel ?? '').trim()
  if (raw === 'Risk-Off') return 'risk_off'
  if (raw === 'Trend') return 'trend'
  if (raw === 'Chop') return 'chop'
  if (tags.has('MeanReversionFavored')) return 'chop'
  return 'unknown'
}

export function computeOverviewPlaybook(input: OverviewImplicationInput): OverviewPlaybook {
  const tags = tagSet(input.regime_rules_tags)
  const defensiveDrift = tags.has('DefensiveDrift')
  const speculativeMania = tags.has('SpeculativeMania')

  const band = nowcastBand(input.nowcast_label ?? null, input.overall_risk_off_score ?? null)
  const tape = regimeTape(input.regime_rules_label ?? null, tags)

  const delta1d = input.delta_1d
  const delta5d = input.delta_5d
  const riskRisingFast =
    (isFiniteNumber(delta1d) && delta1d >= 5) || (isFiniteNumber(delta5d) && delta5d >= 10)

  const nearNeutral =
    isFiniteNumber(input.overall_risk_off_score) &&
    input.overall_risk_off_score > 47 &&
    input.overall_risk_off_score < 53

  const lowConviction =
    (isFiniteNumber(input.confidence) && input.confidence < 0.45) ||
    (isFiniteNumber(input.coverage) && input.coverage < 0.7) ||
    (band === 'neutral' && nearNeutral)

  // --- Base decision (matrix) ---
  let bias: OverviewPlaybookBias = 'balanced'

  if (band === 'risk_off' || tape === 'risk_off' || defensiveDrift) {
    bias = 'defensive'
  } else if (tape === 'trend') {
    bias = band === 'risk_on' && !riskRisingFast ? 'momentum' : 'balanced'
  } else if (tape === 'chop') {
    bias = band === 'risk_on' && !riskRisingFast ? 'balanced' : 'mean_reversion'
  } else {
    bias = 'balanced'
  }

  // Risk rising quickly should downshift aggressiveness.
  if (riskRisingFast && bias === 'momentum') bias = 'balanced'

  return { bias, lowConviction, riskRisingFast, defensiveDrift, speculativeMania }
}

export function buildOverviewImplication(input: OverviewImplicationInput): string {
  const band = nowcastBand(input.nowcast_label ?? null, input.overall_risk_off_score ?? null)
  const tags = tagSet(input.regime_rules_tags)
  const tape = regimeTape(input.regime_rules_label ?? null, tags)
  const { bias, lowConviction, riskRisingFast, defensiveDrift, speculativeMania } = computeOverviewPlaybook(input)

  let base: string
  if (bias === 'defensive') {
    base = 'Stay defensive; favor quality and lower beta.'
  } else if (bias === 'momentum') {
    base = 'Favor momentum leaders and quality; add risk selectively.'
  } else if (bias === 'mean_reversion') {
    base = 'Prefer mean reversion; keep position sizes tight.'
  } else if (tape === 'trend') {
    base = 'Trend backdrop, but risk is mixed; be selective and keep size tighter.'
  } else if (tape === 'chop' && band === 'risk_on') {
    base = 'Choppy tape with constructive risk; trade breakouts selectively and take profits faster.'
  } else {
    base = 'Stay balanced; prioritize quality and clear setups.'
  }

  const notes: string[] = []
  if (lowConviction) {
    notes.push('Low conviction - keep size small.')
  } else if (riskRisingFast) {
    notes.push('Risk is rising quickly - tighten stops.')
  }

  if (defensiveDrift && bias !== 'defensive') {
    notes.push('Defensive drift - lean toward higher quality.')
  }

  if (speculativeMania && band !== 'risk_off') {
    notes.push('Speculative mania - avoid low-quality froth.')
  }

  if (input.cross_asset_label === 'risk_off' && band !== 'risk_off' && !riskRisingFast && !lowConviction) {
    notes.push('Cross-asset stress is elevated.')
  }

  return notes.length ? `${base} ${notes.join(' ')}` : base
}
