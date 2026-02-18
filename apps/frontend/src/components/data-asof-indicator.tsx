'use client'

import { useQuery } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import { formatEasternDateTime, formatEasternMonthDay } from '@/lib/date'
import { TooltipCopyButton } from '@/components/tooltip_copy'
import { api, type PipelineHealth } from '@/lib/api'

function useScorerLastRun() {
  return useQuery<{ lastRun: Date | null; status: string | null }>(
    {
      queryKey: ['pipeline', 'health'],
      queryFn: async () => {
        const data: PipelineHealth = await api.getPipelineHealth()
        const scorer = data.components?.find((c) => c.component === 'scorer')
        const lastRun = scorer?.last_run ? new Date(scorer.last_run) : null
        return { lastRun, status: scorer?.status ?? null }
      },
      staleTime: 60_000,
      refetchInterval: 5 * 60_000,
      enabled: typeof window !== 'undefined',
    }
  )
}

export function DataAsOfIndicator({ className }: { className?: string }) {
  const { data, isLoading, isError } = useScorerLastRun()

  if (isLoading || isError || !data?.lastRun) return null

  const d = data.lastRun
  const desktopLabel = formatEasternMonthDay(d)
  const mobileLabel = formatEasternMonthDay(d)
  const tooltip = formatEasternDateTime(d, 'N/A')

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 text-[11px] text-muted-foreground sm:text-xs',
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          'inline-block h-2 w-2 rounded-full',
          data.status === 'healthy' && 'bg-status-success',
          data.status === 'warning' && 'bg-status-warning',
          data.status === 'error' && 'bg-status-danger',
          !data.status && 'bg-muted-foreground'
        )}
      />
      <span className="hidden md:inline whitespace-nowrap">As of {desktopLabel}</span>
      <span className="md:hidden whitespace-nowrap">As of {mobileLabel}</span>
      <TooltipCopyButton
        tooltipKey="global.asOf"
        label={`Scorer last run: ${tooltip}`}
        iconSize="h-3.5 w-3.5"
        buttonClassName="text-muted-foreground hover:text-foreground"
      />
    </div>
  )
}
