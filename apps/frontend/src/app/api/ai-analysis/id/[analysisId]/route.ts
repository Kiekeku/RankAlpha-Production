import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { redactAiAnalysisPayload } from '@/app/api/_utils/redact'

export async function GET(
  request: NextRequest,
  { params }: { params: { analysisId: string } }
) {
  return proxyGetJson(request, {
    upstreamPath: `/api/v1/ai-analysis/id/${encodeURIComponent(params.analysisId)}`,
    searchParams: request.nextUrl.searchParams,
    revalidate: 120,
    tags: ['ai-analysis', params.analysisId],
    cacheControl: 's-maxage=120, stale-while-revalidate=240',
    auth: 'none',
    transform: SHOW_RAW_DATA ? undefined : redactAiAnalysisPayload,
  })
}
