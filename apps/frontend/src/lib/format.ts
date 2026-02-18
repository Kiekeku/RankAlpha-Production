export function formatPct(x?: number | null, digits = 1) {
  if (x == null || !Number.isFinite(x)) return '-'
  return `${(x * 100).toFixed(digits)}%`
}

export function formatNumberValue(x?: number | null, digits = 2) {
  if (x == null || !Number.isFinite(x)) return '-'
  return Number(x).toFixed(digits)
}

