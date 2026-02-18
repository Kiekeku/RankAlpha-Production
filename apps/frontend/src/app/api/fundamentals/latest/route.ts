import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

type FundamentalsMetric = { metric_code?: string; value?: number | null }
type FundamentalsSnapshot = { metrics?: FundamentalsMetric[]; redacted?: boolean; redaction_reason?: string | null }

function redactFundamentals(snapshot: FundamentalsSnapshot): FundamentalsSnapshot {
  const metrics = Array.isArray(snapshot.metrics) ? snapshot.metrics : []
  return {
    ...snapshot,
    metrics: metrics.map((m) => ({ ...m, value: null })),
    redacted: true,
    redaction_reason: 'license',
  }
}

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/fundamentals/latest',
    searchParams: request.nextUrl.searchParams,
    revalidate: 300,
    tags: ['fundamentals', 'latest'],
    cacheControl: 's-maxage=300, stale-while-revalidate=600',
    auth: 'none',
    transform: SHOW_RAW_DATA ? undefined : redactFundamentals,
  })
}
