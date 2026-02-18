import { AlertTriangleIcon, RefreshCcwIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

export function InlineError({
  message = "Couldn't load data.",
  onRetry,
  retryLabel = 'Retry',
  className,
}: {
  message?: string
  onRetry?: () => void
  retryLabel?: string
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive',
        className,
      )}
      role="status"
    >
      <AlertTriangleIcon className="h-3.5 w-3.5" aria-hidden />
      <span className="font-medium">{message}</span>
      {onRetry ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={onRetry}
        >
          <RefreshCcwIcon className="mr-1 h-3 w-3" aria-hidden />
          {retryLabel}
        </Button>
      ) : null}
    </div>
  )
}

