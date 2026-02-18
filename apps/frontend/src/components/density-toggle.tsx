import { cn } from '@/lib/utils'
import type { UiDensity } from '@/lib/ui_density'

export function DensityToggle({
  value,
  onChange,
  className,
  compactLabels = false,
}: {
  value: UiDensity
  onChange: (next: UiDensity) => void
  className?: string
  compactLabels?: boolean
}) {
  return (
    <div className={cn('inline-flex items-center rounded-full border border-outline/10 bg-card p-1', className)} aria-label="Density">
      <button
        type="button"
        className={cn(
          'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
          value === 'comfortable'
            ? 'bg-background text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground',
        )}
        onClick={() => onChange('comfortable')}
        aria-pressed={value === 'comfortable'}
      >
        {compactLabels ? 'Comfort' : 'Comfortable'}
      </button>
      <button
        type="button"
        className={cn(
          'inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold transition',
          value === 'dense'
            ? 'bg-background text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground',
        )}
        onClick={() => onChange('dense')}
        aria-pressed={value === 'dense'}
      >
        Dense
      </button>
    </div>
  )
}
