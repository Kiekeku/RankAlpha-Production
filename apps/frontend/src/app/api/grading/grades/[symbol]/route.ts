import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'

export async function GET(
  request: NextRequest,
  { params }: { params: { symbol: string } }
) {
  const { symbol } = params

  return proxyGetJson(request, {
    upstreamPath: `/api/v1/grading/grades/${encodeURIComponent(symbol)}`,
    revalidate: 60,
    tags: ['grading', 'grade', symbol],
    cacheControl: 's-maxage=60, stale-while-revalidate=120',
    auth: 'none',
  })
}
