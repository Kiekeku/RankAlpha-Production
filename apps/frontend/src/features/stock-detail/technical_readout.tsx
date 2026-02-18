'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { buildPriceHistoryQuery } from '@/components/price-history-query'
import { formatNumberValue } from '@/lib/format'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

type ReadoutItem = { label: string; value: string }

type PriceHistoryItem = {
  price_date?: string | null
  adj_close_px?: number | null
  close_px?: number | null
}

type PriceHistoryList = {
  items?: PriceHistoryItem[]
}

function latestPrice(items?: PriceHistoryItem[]): number | null {
  if (!Array.isArray(items) || items.length === 0) return null
  let best: PriceHistoryItem | null = null
  for (const item of items) {
    const date = (item?.price_date || '').trim()
    if (!date) continue
    if (!best || date > (best.price_date || '')) {
      best = item
    }
  }
  const candidate = best?.adj_close_px ?? best?.close_px ?? null
  return typeof candidate === 'number' && Number.isFinite(candidate) ? candidate : null
}

export function TechnicalReadout({
  symbol,
  items,
  atrValue,
}: {
  symbol: string
  items: ReadoutItem[]
  atrValue?: number | null
}) {
  const normalized = (symbol || '').trim().toUpperCase()
  const useRawData = SHOW_RAW_DATA
  const { queryKey, queryFn } = buildPriceHistoryQuery(normalized, 252)
  const { data } = useQuery<PriceHistoryList>({
    queryKey,
    queryFn,
    enabled: useRawData && Boolean(normalized),
    staleTime: 60_000,
  })

  const withAtr = useMemo(() => {
    if (!useRawData) return items
    const price = latestPrice(data?.items)
    const atr = atrValue != null && Number.isFinite(atrValue) ? Number(atrValue) : null
    if (price == null || atr == null || price === 0) return items
    const atrPct = (atr / price) * 100
    const atrLabel = `${formatNumberValue(atrPct, 2)}%`
    return items.map((item) => (
      item.label === 'Volatility'
        ? { ...item, value: `${item.value} · ATR% ${atrLabel}` }
        : item
    ))
  }, [atrValue, data?.items, items, useRawData])

  return (
    <div className="rounded-xl border border-outline/10 bg-secondary/10 p-3 text-xs text-muted-foreground">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-foreground">Technical readout</div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {withAtr.map((item) => (
          <div key={item.label} className="flex items-start gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {item.label}:
            </span>
            <span className="text-xs text-muted-foreground">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
