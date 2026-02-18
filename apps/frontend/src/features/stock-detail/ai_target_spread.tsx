'use client'

import { useQuery } from '@tanstack/react-query'

import { api, type LivePrice } from '@/lib/api'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { useHydrated } from '@/lib/use_hydrated'
import { formatSignedPercent } from '@/features/stock-detail/stock_detail_format'

export function AiTargetSpread({
  symbol,
  baseTargetPrice,
}: {
  symbol: string
  baseTargetPrice?: number | null
}) {
  const normalized = (symbol || '').trim().toUpperCase()
  const hydrated = useHydrated()
  const showRawData = SHOW_RAW_DATA
  const shouldQuery = showRawData && hydrated && !!normalized && baseTargetPrice != null
  const { data: livePrice } = useQuery<LivePrice>({
    queryKey: ['live-price', normalized],
    queryFn: () => api.getLivePrice(normalized),
    enabled: shouldQuery,
    refetchInterval: 10000,
    staleTime: 8000,
    retry: false,
    refetchOnWindowFocus: false,
  })

  if (!shouldQuery) return null

  const lastPrice = livePrice && typeof livePrice.last === 'number' ? livePrice.last : undefined
  const prevClose = livePrice && typeof livePrice.close === 'number' ? livePrice.close : undefined
  const currentPrice = lastPrice ?? prevClose
  if (!Number.isFinite(currentPrice) || !Number.isFinite(baseTargetPrice) || currentPrice === 0) {
    return null
  }

  const spreadPct = ((Number(currentPrice) - Number(baseTargetPrice)) / Number(currentPrice)) * 100
  if (!Number.isFinite(spreadPct)) return null

  return (
    <span className="text-[11px] text-muted-foreground">
      - curr-px vs base: {formatSignedPercent(spreadPct, 0)}
    </span>
  )
}
