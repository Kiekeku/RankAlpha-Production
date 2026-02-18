'use client'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function DeltaToggle({
  checked,
  onChange,
  baselineLabel,
  tooltip,
  className,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  baselineLabel?: string | null
  tooltip?: string
  className?: string
}) {
  const baselineText = baselineLabel ? `vs ${baselineLabel}` : 'vs baseline'
  return (
    <label className={cn('flex items-center gap-2 text-xs text-muted-foreground', className)}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded-sm accent-primary"
      />
      <span className="font-semibold uppercase tracking-wide">Show deltas</span>
      <span className="text-[11px] text-muted-foreground">{baselineText}</span>
      {tooltip ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-outline/10 bg-card text-[10px] font-semibold text-muted-foreground transition hover:text-foreground"
                aria-label="Explain deltas"
                onClick={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                }}
              >
                ?
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs px-ds-3 py-ds-2 text-[11px] leading-relaxed">
              {tooltip}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : null}
    </label>
  )
}
