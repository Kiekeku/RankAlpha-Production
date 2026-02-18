import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

type PriceHistoryItem = {
  price_date?: string
  open_px?: number | null
  high_px?: number | null
  low_px?: number | null
  close_px?: number | null
  adj_close_px?: number | null
  volume?: number | null
}

type PriceHistoryList = {
  items?: PriceHistoryItem[]
  normalized?: boolean
  index_base?: number
  redacted?: boolean
  redaction_reason?: string | null
}

function normalizeSeries(list: PriceHistoryList): PriceHistoryList {
  const items = Array.isArray(list.items) ? list.items : []
  if (!items.length) return { ...list, normalized: true, index_base: 100 }

  const sortedAsc = [...items].sort((a, b) => {
    const da = a.price_date || ''
    const db = b.price_date || ''
    return da.localeCompare(db)
  })
  const sortedDesc = [...sortedAsc].reverse()

  const baseAdj = sortedAsc.find((it) => Number.isFinite(Number(it.adj_close_px)))?.adj_close_px ?? null
  const baseClose = sortedAsc.find((it) => Number.isFinite(Number(it.close_px)))?.close_px ?? null

  const scale = (value: number | null | undefined, base: number | null) => {
    if (value == null || base == null) return null
    const v = Number(value)
    const b = Number(base)
    if (!Number.isFinite(v) || !Number.isFinite(b) || b === 0) return null
    return (v / b) * 100
  }

  return {
    ...list,
    normalized: true,
    index_base: 100,
    redacted: true,
    redaction_reason: 'license',
    items: sortedDesc.map((it) => ({
      ...it,
      open_px: scale(it.open_px ?? null, baseClose),
      high_px: scale(it.high_px ?? null, baseClose),
      low_px: scale(it.low_px ?? null, baseClose),
      close_px: scale(it.close_px ?? null, baseClose),
      adj_close_px: scale(it.adj_close_px ?? null, baseAdj),
      volume: null,
    })),
  }
}

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/prices/history',
    searchParams: request.nextUrl.searchParams,
    revalidate: 300,
    tags: ['prices', 'prices-history'],
    cacheControl: 's-maxage=300, stale-while-revalidate=600',
    transform: SHOW_RAW_DATA ? undefined : normalizeSeries,
  })
}
