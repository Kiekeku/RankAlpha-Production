import { cn } from '@/lib/utils'
import { formatEasternDate } from '@/lib/date'

function normalizeCadence(raw?: string | null): string | null {
  const trimmed = (raw || '').trim()
  if (!trimmed) return null
  if (/^updated\s/i.test(trimmed)) return trimmed
  const normalized = trimmed.length > 1 ? `${trimmed[0].toLowerCase()}${trimmed.slice(1)}` : trimmed.toLowerCase()
  return `Updated ${normalized}`
}

export function buildFreshnessLabel(asOf?: string | null, cadence?: string | null): string | null {
  const parts: string[] = []
  if (asOf) parts.push(`As of ${formatEasternDate(asOf)}`)
  const cadenceLabel = normalizeCadence(cadence)
  if (cadenceLabel) parts.push(cadenceLabel)
  if (!parts.length) return null
  return parts.join(' • ')
}

export function DataFreshness({
  asOf,
  cadence,
  className,
}: {
  asOf?: string | null
  cadence?: string | null
  className?: string
}) {
  const label = buildFreshnessLabel(asOf, cadence)
  if (!label) return null
  return (
    <div className={cn('text-[11px] text-muted-foreground sm:text-xs', className)}>
      {label}
    </div>
  )
}

