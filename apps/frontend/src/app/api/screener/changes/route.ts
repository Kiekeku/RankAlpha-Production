import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/screener/changes',
    searchParams: request.nextUrl.searchParams,
    cache: 'no-store',
  })
}
