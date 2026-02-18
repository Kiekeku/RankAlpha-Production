import { NextRequest } from 'next/server'
import { buildAuthHeaders } from '@/app/api/_utils/auth'
import { buildOverviewResponse, createOverviewPartFetcher } from '@/app/api/overview/_utils'

export async function GET(request: NextRequest) {
  const authHeaders = await buildAuthHeaders(request)
  const isAuthed = authHeaders.has('Authorization')
  const fetchPart = createOverviewPartFetcher({ authHeaders, isAuthed, scopeTag: 'nowcast' })

  const [
    nowcastLatest,
    nowcastLatestV2,
    regimeRulesLatest,
    macroLiquidityLatest,
    hyStressLatest,
    volRegimeLatest,
  ] = await Promise.all([
    fetchPart('/api/v1/nowcast/latest', { trail_days: 30 }, { revalidate: 180, tags: ['nowcast', 'nowcast-latest'] }),
    fetchPart(
      '/api/v1/nowcast/latest',
      { model_version: 'nowcast_v2', trail_days: 60 },
      { revalidate: 180, tags: ['nowcast', 'nowcast-latest', 'nowcast-v2'] }
    ),
    fetchPart('/api/v1/screener/regime-rules/latest', undefined, { revalidate: 180, tags: ['screener', 'regime-rules', 'latest'] }),
    fetchPart('/api/v1/macro/liquidity/latest', undefined, { revalidate: 300, tags: ['macro', 'liquidity', 'latest'] }),
    fetchPart('/api/v1/hy-stress/latest', undefined, { revalidate: 300, tags: ['risk', 'hy-stress', 'latest'] }),
    fetchPart('/api/v1/vol-regime', undefined, { revalidate: 300, tags: ['macro', 'vol-regime', 'latest'] }),
  ])

  const payload = {
    nowcastLatest,
    nowcastLatestV2,
    regimeRulesLatest,
    macroLiquidityLatest,
    hyStressLatest,
    volRegimeLatest,
  }

  return buildOverviewResponse(payload, isAuthed)
}
