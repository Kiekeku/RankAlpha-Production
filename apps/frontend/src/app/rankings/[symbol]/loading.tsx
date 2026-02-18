import { Skeleton } from '@/components/ui/skeleton'
import { LoadingStatusNote } from '@/components/loading-status-note'

export default function Loading() {
  return (
    <div className="space-y-3">
      <LoadingStatusNote label="Loading ranking detail…" />
      <Skeleton className="h-10 w-48" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-72 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  )
}
