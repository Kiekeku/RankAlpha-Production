import { cn } from '@/lib/utils'

export type ChartTooltipLine =
  | { type?: 'text'; label?: string; value: string }
  | { type: 'badge'; label: string; value: string; color?: string }

export function ChartTooltip({
  title,
  lines,
  className,
}: {
  title?: string
  lines: ChartTooltipLine[]
  className?: string
}) {
  return (
    <div
      className={cn(
        'rounded-md border border-outline/20 bg-background/95 px-2 py-1 text-[10px] leading-4 text-foreground shadow-sm backdrop-blur-sm',
        className,
      )}
    >
      {title ? <div className="font-semibold text-foreground">{title}</div> : null}
      <div className="space-y-1">
        {lines.map((line, idx) =>
          line.type === 'badge' ? (
            <div key={`line-${idx}`} className="flex items-center gap-2">
              <span
                className="rounded-full px-1.5 py-0.5 text-[9px] font-semibold text-white"
                style={{ backgroundColor: line.color || 'hsl(var(--foreground))' }}
              >
                {line.label}
              </span>
              <span className="font-semibold text-foreground whitespace-nowrap">{line.value}</span>
            </div>
          ) : (
            <div key={`line-${idx}`} className="flex items-center gap-1 text-muted-foreground">
              {line.label ? <span className="font-semibold text-foreground">{line.label}</span> : null}
              <span className="text-foreground">{line.value}</span>
            </div>
          ),
        )}
      </div>
    </div>
  )
}
