import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/vol-regime',
    searchParams: request.nextUrl.searchParams,
    revalidate: 300,
    tags: ['macro', 'vol-regime', 'latest'],
    cacheControl: 's-maxage=300, stale-while-revalidate=900',
  })
}
