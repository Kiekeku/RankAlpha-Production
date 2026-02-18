import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/macro/real-rates/tips10y/series',
    searchParams: request.nextUrl.searchParams,
    revalidate: 300,
    tags: ['macro', 'real-rates', 'tips10y', 'series'],
    cacheControl: 's-maxage=300, stale-while-revalidate=900',
  })
}
