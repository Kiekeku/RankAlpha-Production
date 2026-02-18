import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'

export type HumanTargetBucketMeta = {
  label: string
  Icon: typeof ArrowUpRight
  className: string
}

export function getHumanTargetBucketMeta(bucket?: string | null): HumanTargetBucketMeta | null {
  if (!bucket) return null
  const normalized = bucket.toLowerCase()
  if (normalized.includes('above')) {
    return {
      label: 'Above RA est',
      Icon: ArrowUpRight,
      className:
        'inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-gain',
    }
  }
  if (normalized.includes('below')) {
    return {
      label: 'Below RA est',
      Icon: ArrowDownRight,
      className:
        'inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-loss',
    }
  }
  return {
    label: 'Inline RA est',
    Icon: Minus,
    className:
      'inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground',
  }
}

export function fmtPriceTarget(pt?: number | null): string {
  if (pt == null || Number.isNaN(Number(pt))) return '—'
  return `$${Math.round(Number(pt))}`
}

export function fmtProbability(prob?: number | null): string {
  if (prob == null || Number.isNaN(Number(prob))) return '—'
  return `${Math.round(Number(prob))}%`
}

export function computePct(target?: number | null, base?: number | null): number | undefined {
  if (target == null || base == null || !Number.isFinite(target) || !Number.isFinite(base) || base === 0) return undefined
  return ((target - base) / base) * 100
}

export function fmtPctSigned(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}${Math.abs(Math.round(n))}%`
}

export function fmtBullBearSpread({
  bullDelta,
  bearDelta,
  basePt,
  bullPt,
  bearPt,
}: {
  bullDelta?: number | null
  bearDelta?: number | null
  basePt?: number | null
  bullPt?: number | null
  bearPt?: number | null
}): string {
  const bullFallback = computePct(bullPt, basePt)
  const bearFallback = computePct(bearPt, basePt)
  const bullLabel = fmtPctSigned(bullDelta ?? bullFallback)
  const bearLabel = fmtPctSigned(bearDelta ?? bearFallback)
  return `${bullLabel} / ${bearLabel}`
}
