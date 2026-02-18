'use client'

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { FIVE_MIN_MS } from '@/lib/time'

export function useRankRegimeLatest() {
  return useQuery({
    queryKey: ['rank-regime-latest'],
    queryFn: () => api.getRankRegimeLatest(),
    staleTime: FIVE_MIN_MS,
  })
}

export function useRankRegimeHistory(days: number) {
  return useQuery({
    queryKey: ['rank-regime-history', days],
    queryFn: () => api.getRankRegimeHistory({ days, sort_order: 'asc' }),
    staleTime: FIVE_MIN_MS,
    enabled: Boolean(days),
  })
}

export function useMarketStructureLatest() {
  return useQuery({
    queryKey: ['market-structure-latest'],
    queryFn: () => api.getMarketStructureLatest(),
    staleTime: FIVE_MIN_MS,
  })
}

export function useMarketStructureSeries(limit: number) {
  return useQuery({
    queryKey: ['market-structure-series', limit],
    queryFn: () => api.getMarketStructureSeries({ limit, sort_order: 'desc' }),
    staleTime: FIVE_MIN_MS,
    select: (data) => ({
      ...data,
      items: [...(data.items ?? [])].reverse(),
    }),
  })
}

export function useRegimeSeries(limit: number, enabled = true) {
  return useQuery({
    queryKey: ['regime-series', limit],
    // The backend applies LIMIT after ORDER BY. Request DESC (latest-first) then reverse so
    // charts render left-to-right in chronological order.
    queryFn: () => api.getRegimeSeries({ limit, sort_order: 'desc' }),
    staleTime: FIVE_MIN_MS,
    enabled,
    select: (data) => ({
      ...data,
      items: [...(data.items ?? [])].reverse(),
    }),
  })
}

export function useRegimeLatestIntensity() {
  return useQuery({
    queryKey: ['regime-latest-intensity'],
    queryFn: () => api.getRegimeLatest(),
    staleTime: FIVE_MIN_MS,
  })
}

export function useRegimeLatestRules() {
  return useQuery({
    queryKey: ['regime-latest-rules'],
    queryFn: () => api.getRegimeRulesLatest(),
    staleTime: FIVE_MIN_MS,
  })
}

export function useRegimeRulesSeries(limit: number, enabled = true) {
  return useQuery({
    queryKey: ['regime-rules-series', limit],
    queryFn: () => api.getRegimeRulesSeries({ limit, sort_order: 'asc' }),
    staleTime: FIVE_MIN_MS,
    enabled,
  })
}

export function useBreadthFlow(limit: number) {
  return useQuery({
    queryKey: ['screener-breadth-flow', limit],
    queryFn: () => api.listScreenerBreadthFlow({ limit, sort_order: 'desc' }),
    staleTime: FIVE_MIN_MS,
    select: (data) => ({
      ...data,
      items: [...(data.items ?? [])].reverse(),
    }),
  })
}
