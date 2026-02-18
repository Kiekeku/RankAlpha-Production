import { cn } from '@/lib/utils'

export type ChartLegendItem = {
  label: string
  color: string
  emphasis?: 'primary' | 'secondary'
}

export function ChartLegend({ items, className }: { items: ChartLegendItem[]; className?: string }) {
  if (!items.length) return null
  return (
    <div className={cn('flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground', className)}>
      {items.map((item) => (
        <div key={item.label} className={cn('flex items-center gap-1', item.emphasis === 'primary' && 'text-foreground')}>
          <span
            className={cn('h-[6px] w-[12px] rounded-sm', item.emphasis === 'primary' && 'h-[7px] w-[14px]')}
            style={{ backgroundColor: item.color }}
            aria-hidden="true"
          />
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  )
}
