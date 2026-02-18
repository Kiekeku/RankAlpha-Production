import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { redactAiAnalysisPayload } from '@/app/api/_utils/redact'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/ai-analysis/latest',
    searchParams: request.nextUrl.searchParams,
    revalidate: 120,
    tags: ['ai-analysis', 'ai-analysis-latest'],
    cacheControl: 's-maxage=120, stale-while-revalidate=240',
    transform: SHOW_RAW_DATA ? undefined : redactAiAnalysisPayload,
  })
}
