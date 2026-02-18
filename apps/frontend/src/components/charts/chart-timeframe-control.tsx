import { cn } from '@/lib/utils'

export type ChartTimeframeOption = {
  key: string
  label: string
}

export function ChartTimeframeControl({
  options,
  active,
  onChange,
  className,
}: {
  options: ChartTimeframeOption[]
  active: string
  onChange: (next: string) => void
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-1', className)}>
      {options.map((opt) => (
        <button
          key={opt.key}
          type="button"
          aria-label={`Show ${opt.label} chart`}
          onClick={() => onChange(opt.key)}
          className={cn(
            'rounded-md border px-2 py-0.5 text-[10px] leading-4 font-semibold',
            active === opt.key
              ? 'bg-primary text-primary-foreground border-primary'
              : 'hover:bg-accent text-muted-foreground border-outline/20',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          )}
        >
          {opt.key}
        </button>
      ))}
    </div>
  )
}
