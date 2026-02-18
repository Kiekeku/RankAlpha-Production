import { Skeleton } from '@/components/ui/skeleton'
import { LoadingStatusNote } from '@/components/loading-status-note'
import { cn } from '@/lib/utils'

export function ChartSkeleton({
  className,
  height = 140,
  label = 'Loading chart…',
}: {
  className?: string
  height?: number
  label?: string
}) {
  return (
    <div
      className={cn('rounded-xl border border-outline/10 bg-secondary/15 p-3', className)}
      style={{ height }}
    >
      <LoadingStatusNote label={label} className="mb-2" />
      <div className="flex items-center gap-2">
        <Skeleton className="h-2 w-16" />
        <Skeleton className="h-2 w-10" />
      </div>
      <div className="mt-3 flex h-[calc(100%-28px)] flex-col justify-between">
        <div className="flex-1 rounded-md border border-outline/10 bg-background/40" />
        <div className="mt-3 flex items-center gap-2">
          <Skeleton className="h-2 w-10" />
          <Skeleton className="h-2 w-14" />
        </div>
      </div>
    </div>
  )
}
