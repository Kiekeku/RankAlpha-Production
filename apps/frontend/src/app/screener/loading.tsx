import { Skeleton } from '@/components/ui/skeleton'
import { LoadingStatusNote } from '@/components/loading-status-note'

export default function Loading() {
  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-4 w-[min(56rem,100%)]" />
        <LoadingStatusNote label="Loading Screener…" />
      </div>
      <div className="lg:grid lg:grid-cols-[minmax(0,320px),1fr] lg:items-start lg:gap-6">
        <div className="space-y-3">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
        <div className="mt-4 space-y-3 lg:mt-0">
          {[...Array(12)].map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      </div>
    </div>
  )
}
