import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/screener/sources/meta',
    searchParams: request.nextUrl.searchParams,
    revalidate: 3600,
    tags: ['screener', 'screener-sources', 'screener-sources-meta'],
    cacheControl: 's-maxage=3600, stale-while-revalidate=7200',
    auth: 'none',
  })
}
