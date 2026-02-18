import { cn } from '@/lib/utils'
import { formatEasternDate } from '@/lib/date'

export type DataFreshnessItem = {
  label: string
  asOf?: string | null
  source?: string | null
  version?: string | null
  note?: string | null
  status?: 'ok' | 'mixed' | 'missing'
  missingReason?: string | null
}

function buildMeta(item: DataFreshnessItem): string {
  if (!item.asOf && item.missingReason) {
    return `Unavailable: ${item.missingReason}`
  }
  const parts: string[] = []
  if (item.asOf) parts.push(`As of ${formatEasternDate(item.asOf)}`)
  if (item.source) parts.push(item.source)
  if (item.version) parts.push(item.version)
  if (item.note) parts.push(item.note)
  return parts.length ? parts.join(' • ') : '-'
}

function statusClass(status?: DataFreshnessItem['status']): string {
  if (status === 'missing') return 'text-status-danger'
  if (status === 'mixed') return 'text-status-warning'
  return 'text-foreground'
}

export function DataFreshnessBar({
  items,
  className,
  title = 'Data freshness',
}: {
  items: DataFreshnessItem[]
  className?: string
  title?: string
}) {
  if (!items.length) return null

  return (
    <div className={cn('rounded-2xl border border-outline/10 bg-card px-3 py-3 sm:px-4', className)}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((item) => (
          <div
            key={item.label}
            className="rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2"
          >
            <div className="text-xs font-semibold text-foreground">{item.label}</div>
            <div className={cn('mt-1 text-[11px]', statusClass(item.status))}>
              {buildMeta(item)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
