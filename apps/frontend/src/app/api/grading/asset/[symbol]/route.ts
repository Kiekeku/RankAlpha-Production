import { NextRequest } from 'next/server'
import { proxyGetJson } from '@/app/api/_utils/proxy'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

type AssetDetail = {
  market_cap?: number | null
  beta?: number | null
  target_price?: number | null
  projected_lt_growth_rate?: number | null
  ai_analysis?: {
    market_cap?: number | null
    beta?: number | null
    revenue_cagr_3y?: number | null
    valuation?: {
      pe_forward?: number | null
      ev_ebitda_forward?: number | null
      pe_percentile_in_sector?: number | null
    } | null
  } | null
}

function redactAsset(asset: AssetDetail): AssetDetail {
  const ai = asset.ai_analysis
    ? {
        ...asset.ai_analysis,
        market_cap: null,
        beta: null,
        revenue_cagr_3y: null,
        valuation: asset.ai_analysis.valuation
          ? {
              ...asset.ai_analysis.valuation,
              pe_forward: null,
              ev_ebitda_forward: null,
              pe_percentile_in_sector: null,
            }
          : asset.ai_analysis.valuation,
      }
    : asset.ai_analysis

  return {
    ...asset,
    market_cap: null,
    beta: null,
    target_price: null,
    projected_lt_growth_rate: null,
    ai_analysis: ai,
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: { symbol: string } }
) {
  const symbol = (params.symbol || '').trim().toUpperCase()

  return proxyGetJson(request, {
    upstreamPath: `/api/v1/grading/asset/${encodeURIComponent(symbol)}`,
    searchParams: request.nextUrl.searchParams,
    revalidate: 60,
    tags: ['grading', 'asset', symbol],
    cacheControl: 's-maxage=60, stale-while-revalidate=120',
    auth: 'none',
    transform: SHOW_RAW_DATA ? undefined : redactAsset,
  })
}
