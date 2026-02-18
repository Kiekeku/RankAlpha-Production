import { computeHumanTargetBucket } from '@/lib/human_targets'

type AiAnalysisItem = {
  price_close?: number | null
  price_date?: string | null
  base_price_target?: number | null
  delta_bull_pct?: number | null
  delta_base_pct?: number | null
  delta_bear_pct?: number | null
  nearest_scenario?: string | null
  nearest_distance_pct?: number | null
  human_analyst_targets_provider?: string | null
  human_analyst_targets_query?: string | null
  human_analyst_targets_organic?: any[] | null
  human_analyst_target_low_usd?: number | null
  human_analyst_target_high_usd?: number | null
  human_analyst_target_median_usd?: number | null
  human_analyst_target_mean_usd?: number | null
  human_analyst_target_count?: number | null
  human_target_vs_ra?: string | null
}

function redactAiAnalysisItem(item: AiAnalysisItem): AiAnalysisItem {
  return {
    ...item,
    price_close: null,
    price_date: null,
    delta_bull_pct: null,
    delta_base_pct: null,
    delta_bear_pct: null,
    nearest_scenario: null,
    nearest_distance_pct: null,
    human_target_vs_ra: computeHumanTargetBucket(item),
    human_analyst_targets_provider: null,
    human_analyst_targets_query: null,
    human_analyst_targets_organic: null,
    human_analyst_target_low_usd: null,
    human_analyst_target_high_usd: null,
    human_analyst_target_median_usd: null,
    human_analyst_target_mean_usd: null,
    human_analyst_target_count: null,
  }
}

export function redactAiAnalysisPayload(payload: any): any {
  if (!payload || typeof payload !== 'object') return payload
  if (Array.isArray(payload.items)) {
    const items = payload.items.map((item: AiAnalysisItem) => redactAiAnalysisItem(item))
    return { ...payload, items }
  }
  return {
    ...redactAiAnalysisItem(payload as AiAnalysisItem),
  }
}
