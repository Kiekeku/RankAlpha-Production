export function formatSignedPercent(value?: number | null, digits = 2) {
  if (value === undefined || value === null || !Number.isFinite(value)) {
    return '-'
  }
  const fixed = Math.abs(value).toFixed(digits)
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${fixed}%`
}

export { formatNumberValue } from '@/lib/format'

export function formatUsd(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return '-'
  }
  return Number(value).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function formatUsdCompactFromMillions(valueMillions?: number | null) {
  if (valueMillions === undefined || valueMillions === null || !Number.isFinite(valueMillions)) {
    return '-'
  }
  const usd = Number(valueMillions) * 1_000_000
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(usd)
}

export function formatCompactCount(value?: number | null) {
  if (value === undefined || value === null || !Number.isFinite(value)) {
    return '-'
  }
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(Number(value))
}
