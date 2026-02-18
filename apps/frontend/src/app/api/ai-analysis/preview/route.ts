import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { redactAiAnalysisPayload } from '@/app/api/_utils/redact'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/ai-analysis/preview',
    searchParams: request.nextUrl.searchParams,
    revalidate: 300,
    tags: ['ai-analysis', 'preview'],
    cacheControl: 's-maxage=300, stale-while-revalidate=600',
    transform: SHOW_RAW_DATA ? undefined : redactAiAnalysisPayload,
  })
}
