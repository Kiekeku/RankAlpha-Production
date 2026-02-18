import { cn } from '@/lib/utils'

export const REDACTION_LABEL = 'Licensed Only'

export function RedactedOverlay({
  label = REDACTION_LABEL,
  className,
  badgeClassName,
}: {
  label?: string
  className?: string
  badgeClassName?: string
}) {
  return (
    <div className={cn('pointer-events-none absolute inset-0 flex items-center justify-center', className)}>
      <div className={cn('rounded-md border border-outline/20 bg-background/90 px-2 py-1 text-xs font-semibold text-muted-foreground', badgeClassName)}>
        {label}
      </div>
    </div>
  )
}
