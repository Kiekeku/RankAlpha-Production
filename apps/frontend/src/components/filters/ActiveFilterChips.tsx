import { cn } from '@/lib/utils'

export type ActiveFilterChip = {
  key?: string
  label: string
  onRemove?: () => void
}

export function ActiveFilterChips({
  chips,
  onClearAll,
  clearLabel = 'Clear all',
  emptyLabel = 'No active filters.',
  className,
}: {
  chips: ActiveFilterChip[]
  onClearAll?: () => void
  clearLabel?: string
  emptyLabel?: string
  className?: string
}) {
  const hasChips = chips.length > 0
  const canClear = Boolean(onClearAll)

  return (
    <div className={cn('flex flex-wrap items-center gap-2 text-xs', className)}>
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Active filters</span>
      <div className="flex flex-wrap items-center gap-2">
        {hasChips ? (
          chips.map((chip, idx) => (
            <span
              key={chip.key || `${chip.label}-${idx}`}
              className="inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-2.5 py-1 text-xs font-semibold text-muted-foreground"
            >
              <span>{chip.label}</span>
              {chip.onRemove ? (
                <button
                  type="button"
                  className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground transition hover:bg-secondary/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  onClick={chip.onRemove}
                  aria-label={`Remove filter ${chip.label}`}
                >
                  ×
                </button>
              ) : null}
            </span>
          ))
        ) : (
          <span className="text-xs text-muted-foreground">{emptyLabel}</span>
        )}
      </div>
      {canClear ? (
        <button
          type="button"
          className={cn(
            'ml-auto inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:border-outline/20 hover:text-foreground',
            !hasChips && 'cursor-not-allowed opacity-50 hover:border-outline/10 hover:text-muted-foreground',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          )}
          onClick={onClearAll}
          disabled={!hasChips}
        >
          {clearLabel}
        </button>
      ) : null}
    </div>
  )
}
