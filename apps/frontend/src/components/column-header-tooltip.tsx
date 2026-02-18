import { TooltipCopyButton } from '@/components/tooltip_copy'
import { cn } from '@/lib/utils'
import type { TooltipKey } from '@/lib/tooltip_copy'

export function ColumnHeaderTooltip({
  label,
  tooltipKey,
  className,
}: {
  label: string
  tooltipKey: TooltipKey
  className?: string
}) {
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <span>{label}</span>
      <TooltipCopyButton tooltipKey={tooltipKey} iconSize="h-3 w-3" buttonClassName="text-muted-foreground/70" />
    </span>
  )
}

