import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: any[]) {
  return twMerge(clsx(inputs))
}

export function formatScore(score?: number | null): string {
  if (score === undefined || score === null) return 'N/A'
  const numeric = Number(score)
  if (!Number.isFinite(numeric)) return 'N/A'
  const rounded = Math.round(numeric)
  return String(rounded)
}
