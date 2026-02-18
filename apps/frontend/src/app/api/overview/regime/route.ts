import { NextRequest } from 'next/server'
import { buildAuthHeaders } from '@/app/api/_utils/auth'
import { buildOverviewResponse, createOverviewPartFetcher } from '@/app/api/overview/_utils'

export async function GET(request: NextRequest) {
  const authHeaders = await buildAuthHeaders(request)
  const isAuthed = authHeaders.has('Authorization')
  const fetchPart = createOverviewPartFetcher({ authHeaders, isAuthed, scopeTag: 'regime' })

  const [
    rankRegimeLatest,
    rankRegimeHistory180,
    marketStructureLatest,
    marketStructureSeries180,
    regimeLatestIntensity,
    regimeLatestRules,
    regimeSeries180,
    regimeRulesSeries180,
    screenerBreadthFlow120,
  ] = await Promise.all([
    fetchPart('/api/v1/signals/rank-regime', undefined, { revalidate: 180, tags: ['signals', 'rank-regime', 'latest'] }),
    fetchPart('/api/v1/signals/rank-regime/history', { days: 180, sort_order: 'asc' }, { revalidate: 300, tags: ['signals', 'rank-regime', 'history'] }),
    fetchPart('/api/v1/market-structure/latest', undefined, { revalidate: 180, tags: ['market-structure', 'latest'] }),
    fetchPart('/api/v1/market-structure/series', { limit: 180, skip: 0, sort_order: 'desc' }, { revalidate: 300, tags: ['market-structure', 'series'] }),
    fetchPart('/api/v1/screener/regime/latest', undefined, { revalidate: 180, tags: ['screener', 'regime', 'latest'] }),
    fetchPart('/api/v1/screener/regime-rules/latest', undefined, { revalidate: 180, tags: ['screener', 'regime-rules', 'latest'] }),
    fetchPart('/api/v1/screener/regime/series', { limit: 180, sort_order: 'desc' }, { revalidate: 300, tags: ['screener', 'regime', 'series', '180'] }),
    fetchPart('/api/v1/screener/regime-rules/series', { limit: 180, skip: 0, sort_order: 'asc' }, { revalidate: 300, tags: ['screener', 'regime-rules', 'series', '180'] }),
    fetchPart('/api/v1/screener/breadth/flow', { limit: 120, sort_order: 'desc' }, { revalidate: 300, tags: ['screener', 'breadth', 'flow', '120'] }),
  ])

  const payload = {
    rankRegimeLatest,
    rankRegimeHistory180,
    marketStructureLatest,
    marketStructureSeries180,
    regimeLatestIntensity,
    regimeLatestRules,
    regimeSeries180,
    regimeRulesSeries180,
    screenerBreadthFlow120,
  }

  return buildOverviewResponse(payload, isAuthed)
}
