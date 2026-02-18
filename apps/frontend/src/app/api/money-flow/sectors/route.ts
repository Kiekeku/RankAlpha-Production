import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/money-flow/sectors',
    searchParams: request.nextUrl.searchParams,
    revalidate: 600,
    tags: ['money-flow', 'sectors', 'latest'],
    cacheControl: 's-maxage=600, stale-while-revalidate=1800',
  })
}
