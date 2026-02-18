import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(request: NextRequest) {
  return proxyGetJson(request, {
    upstreamPath: '/api/v1/pipeline/health',
    revalidate: 60,
    tags: ['pipeline', 'health'],
    cacheControl: 's-maxage=60, stale-while-revalidate=120',
  })
}
