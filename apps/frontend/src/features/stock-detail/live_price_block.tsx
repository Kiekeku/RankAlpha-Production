'use client'

import { useQuery } from '@tanstack/react-query'
import { Skeleton } from '@/components/ui/skeleton'
import { api, LivePrice } from '@/lib/api'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { useHydrated } from '@/lib/use_hydrated'
import { REDACTION_LABEL } from '@/components/ui/redacted'
import { cn } from '@/lib/utils'
import { formatSignedPercent, formatUsd } from '@/features/stock-detail/stock_detail_format'

export function LivePriceBlock({
  symbol,
  variant = 'default',
}: {
  symbol: string
  variant?: 'default' | 'compact'
}) {
  const normalized = (symbol || '').trim().toUpperCase()
  const isCompact = variant === 'compact'
  const showRawData = SHOW_RAW_DATA
  const hydrated = useHydrated()
  const shouldQuery = showRawData && !!normalized && hydrated
  const { data: livePrice, isLoading, isError } = useQuery<LivePrice>({
    queryKey: ['live-price', normalized],
    queryFn: () => api.getLivePrice(normalized),
    enabled: shouldQuery,
    refetchInterval: 10000,
    staleTime: 8000,
    retry: false,
    refetchOnWindowFocus: false,
  })

  const lastPrice = livePrice && typeof livePrice.last === 'number' ? livePrice.last : undefined
  const prevClose = livePrice && typeof livePrice.close === 'number' ? livePrice.close : undefined
  const isRealtime = Boolean(livePrice?.is_realtime)
  const brokerChangePct =
    livePrice && typeof livePrice.change_pct === 'number' && Number.isFinite(livePrice.change_pct)
      ? livePrice.change_pct
      : null
  const displayPrice = lastPrice ?? prevClose
  const realTimeChangePct =
    brokerChangePct !== null
      ? brokerChangePct
      : lastPrice !== undefined && prevClose !== undefined && prevClose !== 0
        ? ((lastPrice - prevClose) / prevClose) * 100
        : null
  const showLoading = showRawData && (!hydrated || isLoading)

  return (
    <div
      className={cn(
        'flex min-w-[0] flex-wrap items-center gap-2 text-left tabular-nums sm:flex-nowrap sm:justify-end sm:text-right',
        isCompact && 'gap-1 sm:gap-1.5',
      )}
    >
      <span className={cn('text-xs uppercase tracking-wide text-muted-foreground', isCompact && 'sr-only')}>
        {isRealtime ? 'Live Price' : 'Last Price'}
      </span>
      <div className={cn('flex min-h-[1.75rem] flex-nowrap items-center gap-2 sm:justify-end', isCompact && 'min-h-0 gap-1')}>
        {!showRawData ? (
          <div className="flex items-center gap-2">
            <span className={cn('text-lg font-mono font-semibold leading-none tracking-tight blur-sm select-none', isCompact && 'text-sm')}>$----.--</span>
            <span className={cn('text-sm font-medium blur-sm select-none', isCompact && 'text-xs')}>+--.--%</span>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{REDACTION_LABEL}</span>
          </div>
        ) : showLoading ? (
          <Skeleton className={cn('h-6 w-20', isCompact && 'h-5 w-16')} />
        ) : isError ? (
          <span className="text-xs text-destructive">Unavailable</span>
        ) : (
          <>
            <span className={cn('text-lg font-mono font-semibold leading-none tracking-tight', isCompact && 'text-sm')}>
              {formatUsd(displayPrice)}
            </span>
            {realTimeChangePct !== null && (
              <span className={cn(`min-h-[1.1rem] text-sm font-medium ${realTimeChangePct >= 0 ? 'text-gain' : 'text-loss'}`, isCompact && 'min-h-0 text-xs')}>
                {formatSignedPercent(realTimeChangePct)}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  )
}
