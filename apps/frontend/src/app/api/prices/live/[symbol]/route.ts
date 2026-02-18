import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

type LivePricePayload = {
  symbol?: string
  bid?: number | null
  ask?: number | null
  last?: number | null
  close?: number | null
  change_pct?: number | null
  account?: string | null
  is_realtime?: boolean | null
  raw?: Record<string, unknown> | null
  redacted?: boolean
  redaction_reason?: string | null
}

function redactLivePrice(payload: LivePricePayload): LivePricePayload {
  if (!payload || typeof payload !== 'object') return payload
  return {
    ...payload,
    bid: null,
    ask: null,
    last: null,
    close: null,
    change_pct: null,
    is_realtime: false,
    raw: null,
    redacted: true,
    redaction_reason: 'license',
  }
}

export async function GET(request: NextRequest, { params }: { params: { symbol: string } }) {
  const symbol = (params.symbol || '').trim().toUpperCase()
  return proxyGetJson(request, {
    upstreamPath: `/api/v1/prices/live/${encodeURIComponent(symbol)}`,
    searchParams: request.nextUrl.searchParams,
    cache: 'no-store',
    transform: SHOW_RAW_DATA ? undefined : redactLivePrice,
  })
}
