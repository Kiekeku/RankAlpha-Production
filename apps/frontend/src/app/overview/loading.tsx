import { Skeleton } from '@/components/ui/skeleton'
import { LoadingStatusNote } from '@/components/loading-status-note'

export default function Loading() {
  return (
    <div className="space-y-4">
      <LoadingStatusNote label="Loading Overview…" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  )
}
