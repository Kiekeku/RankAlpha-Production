import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/earnings/upcoming',
    searchParams: request.nextUrl.searchParams,
    revalidate: 300,
    tags: ['earnings', 'earnings-upcoming'],
    cacheControl: 's-maxage=300, stale-while-revalidate=900',
  })
}
