'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { DataFreshnessBar, type DataFreshnessItem } from '@/components/data/data-freshness-bar'
import { buildPriceHistoryQuery } from '@/components/price-history-query'
import type { PriceHistoryList } from '@/lib/api'
import { useHydrated } from '@/lib/use_hydrated'

function latestPriceDate(data?: PriceHistoryList | null): string | null {
  const items = Array.isArray(data?.items) ? data!.items : []
  if (!items.length) return null
  let latest = ''
  for (const item of items) {
    const date = (item?.price_date || '').trim()
    if (date && date > latest) latest = date
  }
  return latest || null
}

export function TickerFreshnessBar({
  symbol,
  items,
  days = 252,
  enablePriceHistory = true,
  priceFallbackAsOf = null,
  className,
  title,
}: {
  symbol: string
  items: DataFreshnessItem[]
  days?: number
  enablePriceHistory?: boolean
  priceFallbackAsOf?: string | null
  className?: string
  title?: string
}) {
  const normalizedSymbol = (symbol || '').trim().toUpperCase()
  const hydrated = useHydrated()
  const { queryKey, queryFn } = buildPriceHistoryQuery(normalizedSymbol, days)
  const { data } = useQuery<PriceHistoryList>({
    queryKey,
    queryFn,
    enabled: enablePriceHistory && Boolean(normalizedSymbol) && hydrated,
    staleTime: 60_000,
  })

  const priceAsOf = useMemo(() => {
    const fromHistory = enablePriceHistory && hydrated ? latestPriceDate(data) : null
    return fromHistory ?? priceFallbackAsOf ?? null
  }, [data, enablePriceHistory, hydrated, priceFallbackAsOf])
  const mergedItems = useMemo<DataFreshnessItem[]>(() => {
    const priceItem: DataFreshnessItem = {
      label: 'Prices',
      asOf: priceAsOf,
      status: priceAsOf ? 'ok' : 'missing',
      missingReason: priceAsOf ? null : 'Price unavailable',
    }
    return [priceItem, ...items]
  }, [items, priceAsOf])

  return <DataFreshnessBar items={mergedItems} className={className} title={title} />
}
