import { NextRequest } from 'next/server'
import { buildAuthHeaders } from '@/app/api/_utils/auth'
import { buildOverviewResponse, createOverviewPartFetcher } from '@/app/api/overview/_utils'

export async function GET(request: NextRequest) {
  const authHeaders = await buildAuthHeaders(request)
  const isAuthed = authHeaders.has('Authorization')
  const fetchPart = createOverviewPartFetcher({ authHeaders, isAuthed, scopeTag: 'macro' })

  const [
    macroLiquidityLatest,
    macroLiquiditySeriesRrp,
    macroLiquiditySeriesTga,
    macroNetLiquidityLatest,
    macroNetLiquiditySeries,
    hyStressLatest,
    hyStressSeries,
    fraOisLatest,
    fraOisSeries36,
    volRegimeLatest,
    macroPutCallEquitySeries,
    macroPutCallSpxSeries,
    benchmarkSeriesUsdx,
    benchmarkSeriesXau,
    benchmarkSeriesWti,
    treasurySeries2y,
    treasurySeries10y,
    treasurySeriesOn,
    tips10ySeries,
    pricesHistoryTlt,
    pricesHistoryEmb,
    fxSeriesUsdjpy,
    fxSeriesCnyusd,
    breadthLatest,
    breadthSeriesSpxExposure,
    breadthSeriesNdxExposure,
    breadthSeriesNyseAd,
    moneyFlowSectors,
    moneyFlowSectorSeries,
  ] = await Promise.all([
    fetchPart('/api/v1/macro/liquidity/latest', undefined, { revalidate: 300, tags: ['macro', 'liquidity', 'latest'] }),
    fetchPart(
      '/api/v1/macro/liquidity/series',
      { series: 'on_rrp', sort_order: 'desc', limit: 180, skip: 0 },
      { revalidate: 300, tags: ['macro', 'liquidity', 'series', 'on_rrp'] }
    ),
    fetchPart(
      '/api/v1/macro/liquidity/series',
      { series: 'tga', sort_order: 'desc', limit: 180, skip: 0 },
      { revalidate: 300, tags: ['macro', 'liquidity', 'series', 'tga'] }
    ),
    fetchPart('/api/v1/macro/liquidity/net-liquidity/latest', { lookback_weeks: 520 }, { revalidate: 300, tags: ['macro', 'liquidity', 'net-liquidity', 'latest'] }),
    fetchPart('/api/v1/macro/liquidity/net-liquidity/series', { sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['macro', 'liquidity', 'net-liquidity', 'series'] }),
    fetchPart('/api/v1/hy-stress/latest', undefined, { revalidate: 300, tags: ['risk', 'hy-stress', 'latest'] }),
    fetchPart('/api/v1/hy-stress/series', { sort_order: 'desc', limit: 252, skip: 0 }, { revalidate: 300, tags: ['risk', 'hy-stress', 'series'] }),
    fetchPart('/api/v1/fra-ois/latest', { fra_source: 'SR3' }, { revalidate: 300, tags: ['rates', 'fra-ois', 'latest'] }),
    fetchPart(
      '/api/v1/fra-ois/series',
      { fra_source: 'SR3', start_months: 3, end_months: 6, sort_order: 'desc', limit: 252, skip: 0 },
      { revalidate: 300, tags: ['rates', 'fra-ois', 'series', '3x6'] }
    ),
    fetchPart('/api/v1/vol-regime', undefined, { revalidate: 300, tags: ['macro', 'vol-regime', 'latest'] }),
    fetchPart(
      '/api/v1/macro/put-call/series',
      { series: 'equity', sort_order: 'desc', limit: 252, skip: 0 },
      { revalidate: 300, tags: ['macro', 'put-call', 'series', 'equity'] }
    ),
    fetchPart(
      '/api/v1/macro/put-call/series',
      { series: 'spx', sort_order: 'desc', limit: 252, skip: 0 },
      { revalidate: 300, tags: ['macro', 'put-call', 'series', 'spx'] }
    ),
    fetchPart('/api/v1/benchmarks/series', { benchmark_name: '$USDX', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['benchmarks', 'series', '$USDX'] }),
    fetchPart('/api/v1/benchmarks/series', { benchmark_name: 'XAUUSD', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['benchmarks', 'series', 'XAUUSD'] }),
    fetchPart('/api/v1/benchmarks/series', { benchmark_name: '@WTI', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['benchmarks', 'series', '@WTI'] }),
    fetchPart('/api/v1/rates/treasury/series', { tenor: '2Y', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['rates', 'treasury', 'series', '2Y'] }),
    fetchPart('/api/v1/rates/treasury/series', { tenor: '10Y', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['rates', 'treasury', 'series', '10Y'] }),
    fetchPart('/api/v1/rates/treasury/series', { tenor: 'O/N', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['rates', 'treasury', 'series', 'O/N'] }),
    fetchPart('/api/v1/macro/real-rates/tips10y/series', { sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['macro', 'real-rates', 'tips10y', 'series'] }),
    fetchPart('/api/v1/prices/history', { symbol: 'TLT', limit: 260, skip: 0 }, { revalidate: 300, tags: ['prices', 'history', 'TLT'] }),
    fetchPart('/api/v1/prices/history', { symbol: 'EMB', limit: 260, skip: 0 }, { revalidate: 300, tags: ['prices', 'history', 'EMB'] }),
    fetchPart('/api/v1/fx/series', { pair: 'USDJPY', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['fx', 'series', 'USDJPY'] }),
    fetchPart('/api/v1/fx/series', { pair: 'CNYUSD', sort_order: 'desc', limit: 260, skip: 0 }, { revalidate: 300, tags: ['fx', 'series', 'CNYUSD'] }),
    fetchPart('/api/v1/breadth/latest', undefined, { revalidate: 300, tags: ['breadth', 'latest'] }),
    fetchPart(
      '/api/v1/breadth/series',
      { universe: 'SPX', indicator: 'target_exposure', sort_order: 'desc', limit: 252, skip: 0 },
      { revalidate: 300, tags: ['breadth', 'series', 'SPX', 'target_exposure'] }
    ),
    fetchPart(
      '/api/v1/breadth/series',
      { universe: 'NDX', indicator: 'target_exposure', sort_order: 'desc', limit: 252, skip: 0 },
      { revalidate: 300, tags: ['breadth', 'series', 'NDX', 'target_exposure'] }
    ),
    fetchPart(
      '/api/v1/breadth/series',
      { universe: 'NYSE', indicator: 'ad_ratio', sort_order: 'desc', limit: 252, skip: 0 },
      { revalidate: 300, tags: ['breadth', 'series', 'NYSE', 'ad_ratio'] }
    ),
    fetchPart('/api/v1/money-flow/sectors', undefined, { revalidate: 600, tags: ['money-flow', 'sectors', 'latest'] }),
    fetchPart('/api/v1/money-flow/sectors/series', { days: 180 }, { revalidate: 600, tags: ['money-flow', 'sectors', 'series'] }),
  ])

  const payload = {
    macroLiquidityLatest,
    macroLiquiditySeriesRrp,
    macroLiquiditySeriesTga,
    macroNetLiquidityLatest,
    macroNetLiquiditySeries,
    hyStressLatest,
    hyStressSeries,
    fraOisLatest,
    fraOisSeries36,
    volRegimeLatest,
    macroPutCallEquitySeries,
    macroPutCallSpxSeries,
    benchmarkSeriesUsdx,
    benchmarkSeriesXau,
    benchmarkSeriesWti,
    treasurySeries2y,
    treasurySeries10y,
    treasurySeriesOn,
    tips10ySeries,
    pricesHistoryTlt,
    pricesHistoryEmb,
    fxSeriesUsdjpy,
    fxSeriesCnyusd,
    breadthLatest,
    breadthSeriesSpxExposure,
    breadthSeriesNdxExposure,
    breadthSeriesNyseAd,
    moneyFlowSectors,
    moneyFlowSectorSeries,
  }

  return buildOverviewResponse(payload, isAuthed)
}
