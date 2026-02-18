import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/signals/rank-regime',
    searchParams: request.nextUrl.searchParams,
    revalidate: 180,
    tags: ['signals', 'rank-regime', 'latest'],
    cacheControl: 's-maxage=180, stale-while-revalidate=600',
    auth: 'none',
  })
}
