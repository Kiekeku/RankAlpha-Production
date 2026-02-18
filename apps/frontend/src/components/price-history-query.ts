'use client'

import { api, type PriceHistoryList } from '@/lib/api'

export type PriceHistoryQuery = {
  queryKey: (string | number)[]
  queryFn: () => Promise<PriceHistoryList>
  fetchLimit: number
}

export function buildPriceHistoryQuery(symbol: string, days: number): PriceHistoryQuery {
  const normalized = (symbol || '').trim().toUpperCase()
  const fetchLimit = Math.min(Math.ceil(days * 2), 600)

  return {
    queryKey: ['price-history-mini', normalized, days, fetchLimit],
    queryFn: () => api.getPriceHistory({ symbol: normalized, limit: fetchLimit }),
    fetchLimit,
  }
}
