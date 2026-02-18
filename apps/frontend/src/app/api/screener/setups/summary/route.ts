import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/screener/setups/summary',
    searchParams: request.nextUrl.searchParams,
    revalidate: 120,
    tags: ['screener', 'setups'],
    cacheControl: 's-maxage=120, stale-while-revalidate=300',
  })
}
