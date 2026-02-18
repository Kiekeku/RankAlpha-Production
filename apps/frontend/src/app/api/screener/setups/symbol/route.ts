import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/screener/setups/symbol',
    searchParams: request.nextUrl.searchParams,
    revalidate: 60,
    tags: ['screener', 'setups'],
    cacheControl: 's-maxage=60, stale-while-revalidate=180',
  })
}
