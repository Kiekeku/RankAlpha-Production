import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

type LatestAdjItem = {
  close_px?: number | null
  adj_close_px?: number | null
  volume?: number | null
}

type LatestAdjList = {
  items?: LatestAdjItem[]
  redacted?: boolean
  redaction_reason?: string | null
}

function redactLatest(list: LatestAdjList): LatestAdjList {
  const items = Array.isArray(list.items) ? list.items : []
  return {
    ...list,
    redacted: true,
    redaction_reason: 'license',
    items: items.map((it) => ({
      ...it,
      close_px: null,
      adj_close_px: null,
      volume: null,
    })),
  }
}

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/prices/latest',
    searchParams: request.nextUrl.searchParams,
    revalidate: 300,
    tags: ['prices', 'prices-latest'],
    cacheControl: 's-maxage=300, stale-while-revalidate=600',
    transform: SHOW_RAW_DATA ? undefined : redactLatest,
  })
}
