import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/market-structure/latest',
    searchParams: request.nextUrl.searchParams,
    revalidate: 180,
    tags: ['market-structure', 'latest'],
    cacheControl: 's-maxage=180, stale-while-revalidate=600',
    auth: 'none',
  })
}
