import axios from 'axios'

const INTERNAL_API_BASE = (process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://api:6080').replace(/\/$/, '')
const BACKEND_PREFIX = '/api/v1'
const FRONTEND_PREFIX = '/api'

function buildUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`

  if (typeof window === 'undefined') {
    return `${INTERNAL_API_BASE}${BACKEND_PREFIX}${normalizedPath}`
  }

  return `${FRONTEND_PREFIX}${normalizedPath}`
}

// ----- Types used in existing pages -----
export interface StockGradeItem {
  symbol: string
  company_name?: string
  sector?: string
  momentum_score?: number
  value_score?: number
  sentiment_score?: number
  overall_grade: string
  grade_explanation: string
  confidence: string
  date: string
}

export interface GradeLeaderboard {
  stocks: StockGradeItem[]
  total_count: number
  page: number
  page_size: number
  as_of_date?: string
  ai_preview?: Record<string, AiPreview>
}

export interface PeerGradeItem {
  symbol: string
  company_name?: string
  as_of_date?: string | null
  overall_grade: string
}

export interface AiPreview {
  events_count?: number
  base_price_target?: number
  has_thesis?: boolean
}

export interface HumanAnalystTargetOrganicItem {
  position?: number
  title?: string
  link?: string
  snippet?: string
  date?: string
  amounts_usd?: number[]
}

export interface PipelineHealthComponent {
  component: string
  status: string
  last_run?: string
  records_processed?: number
  message: string
  latest_date?: string
  gap_bdays?: number
  price_latest_date?: string
  screener_latest_date?: string
  screener_last_run?: string
}

export interface PipelineHealth {
  overall_status: string
  components: PipelineHealthComponent[]
  data_freshness?: any[]
  last_check?: string
  thresholds?: {
    ingestion_healthy_max_bdays: number
    ingestion_warning_max_bdays: number
    scorer_healthy_max_bdays: number
    sentiment_healthy_max_bdays: number
  }
}

export interface StockGrade {
  symbol: string
  company_name?: string
  date: string
  momentum_score?: number
  value_score?: number
  sentiment_score?: number
  overall_grade: string
  grade_explanation: string
  confidence: string
}

export interface ModelWeights {
  as_of_date: string
  method: string
  window_days: number
  horizon_days: number
  w_momentum: number
  w_value: number
  w_sentiment: number
  lambda_rp: number
  alpha_shrink: number
  sentiment_coverage?: number | null
  source: 'db' | 'default'
}

export interface AssetDetail {
  symbol: string
  company_name?: string
  sector?: string
  exchange?: string
  market_cap?: number
  beta?: number
  target_price?: number
  projected_lt_growth_rate?: number
  next_earnings_date?: string | null
  next_earnings_time?: string | null
  next_earnings_source?: string | null
  current_grade: StockGrade
  score_history: { date: string; score_type: string; score: number }[]
  recent_news: { headline: string; analysis_date?: string; type: string }[]
  ai_analysis?: {
    analysis_date?: string
    source_name?: string
    commentary?: string
    market_cap?: number
    beta?: number
    news_sentiment_30d?: number
    social_sentiment_7d?: number
    sentiment_proxy_score?: number
    sentiment_proxy_date?: string
    revenue_cagr_3y?: number
    rate_sensitivity?: number
    fx_sensitivity?: string
    commodity_exposure?: string
    options_skew_30d?: number
    short_interest_pct?: number
    employee_score?: number
    headline_buzz?: string
    valuation?: {
      pe_forward?: number
      ev_ebitda_forward?: number
      pe_percentile_in_sector?: number
    }
    factor_scores?: {
      value?: number
      quality?: number
      momentum?: number
      low_vol?: number
    }
    scenarios?: {
      bull?: { price?: number; probability_pct?: number }
      base?: { price?: number; probability_pct?: number }
      bear?: { price?: number; probability_pct?: number }
    }
    catalysts?: {
      shortTerm?: any[]
      longTerm?: any[]
    }
    events?: any[]
    risks?: { macro?: string[]; headline?: string[]; data_gaps?: string[] }
    peers?: any[]
    analyst_summary?: { bull_case?: string; bear_case?: string; valuation_check?: string }
  }
}

// ----- Types for AI Analysis view -----
export interface AiAnalysisItem {
  analysis_id: string
  as_of_date: string
  symbol: string
  company_name?: string
  asset_type?: string
  source_name?: string
  market_cap_usd?: number
  revenue_cagr_3y_pct?: number
  gross_margin_trend?: string
  net_margin_trend?: string
  free_cash_flow_trend?: string
  insider_activity?: string
  beta_sp500?: number
  rate_sensitivity_bps?: number
  fx_sensitivity?: string
  commodity_exposure?: string
  news_sentiment_30d?: number
  social_sentiment_7d?: number
  options_skew_30d?: number
  short_interest_pct_float?: number
  employee_glassdoor_score?: number
  headline_buzz_score?: string
  commentary?: string
  overall_rating?: string
  confidence?: string
  recommendation_timeframe?: string
  pe_forward?: number
  ev_ebitda_forward?: number
  pe_percentile_in_sector?: number
  value_score?: number
  quality_score?: number
  momentum_score?: number
  low_vol_score?: number
  bull_price_target?: number
  bull_probability_pct?: number
  base_price_target?: number
  base_probability_pct?: number
  bear_price_target?: number
  bear_probability_pct?: number
  short_catalysts?: any[]
  long_catalysts?: any[]
  events?: any[]
  macro_risks?: string[]
  headline_risks?: string[]
  data_gaps?: string[]
  peers?: any[]
  analyst_summary?: { bull_case?: string; bear_case?: string; valuation_check?: string }
  human_analyst_targets_provider?: string
  human_analyst_targets_query?: string
  human_analyst_targets_organic?: HumanAnalystTargetOrganicItem[]
  human_analyst_target_low_usd?: number
  human_analyst_target_high_usd?: number
  human_analyst_target_median_usd?: number
  human_analyst_target_mean_usd?: number
  human_analyst_target_count?: number
  human_target_vs_ra?: string

  // Proximity (optional)
  price_close?: number
  price_date?: string
  delta_bull_pct?: number
  delta_base_pct?: number
  delta_bear_pct?: number
  nearest_scenario?: string
  nearest_distance_pct?: number
}

export interface AiAnalysisList {
  items: AiAnalysisItem[]
  total_count: number
  page: number
  page_size: number
}

// ----- Screener consensus types -----
export interface ScreenerConsensusItem {
  as_of_date: string
  symbol: string
  company_name?: string
  sector?: string
  exchange?: string
  primary_source?: string
  primary_style?: string
  appearances: number
  styles_distinct: number
  sources_distinct: number
  rank_best?: number
  rank_avg?: number
  rank_median?: number
  min_style_rank_pct?: number
  long_score_raw?: number
  short_score_raw?: number
  net_score_raw?: number
  families_count_long?: number
  families_count_short?: number
  screens_count_long?: number
  screens_count_short?: number
  tier12_hits_long?: number
  tier12_hits_short?: number
  breadth_bonus_long?: number
  any_bonus_long?: number
  family_streak_bonus_long?: number
  any_bonus_short?: number
  family_streak_bonus_short?: number
  long_pct?: number
  short_pct?: number
  net_pct?: number
  consensus_score?: number
}

export interface ScreenerConsensusList {
  items: ScreenerConsensusItem[]
  total_count: number
  page: number
  page_size: number
}

export interface OptionCount { name: string; count: number }

// ----- Screener change types -----
export type ScreenerChangeType = 'entered' | 'reentered' | 'dropped'

export interface ScreenerChangeItem {
  change_date: string
  symbol: string
  regime_bias?: 'Bullish' | 'Bearish'
  position_side?: 'long' | 'short'
  company_name?: string
  sector?: string
  exchange?: string
  source: string
  style?: string
  change_type: ScreenerChangeType
  current_rank?: number
  previous_rank?: number
  rank_delta?: number
  last_seen_date?: string
  days_since_last_seen?: number
  absent_trading_days?: number
}

export interface ScreenerChangeList {
  items: ScreenerChangeItem[]
  total_count: number
  page: number
  page_size: number
}

export interface ScreenerBreadthItem {
  change_date: string
  style_key: number
  style_name: string
  position_side: string
  regime_bias: 'Bullish' | 'Bearish'
  entered_count: number
  reentered_count: number
  dropped_count: number
  eligible_count: number
  entered_pct: number
  dropped_pct: number
  net_pct: number
  net_pct_signed: number
  entered_pct_avg_5d: number
  dropped_pct_avg_5d: number
  net_pct_avg_5d: number
  net_pct_avg_5d_signed: number
}

export interface ScreenerBreadthList {
  items: ScreenerBreadthItem[]
  total_count: number
  page: number
  page_size: number
}

export interface ScreenerBreadthFlowItem {
  change_date: string
  canonical_name: string
  regime_bias: 'Bullish' | 'Bearish'
  entered_count: number
  dropped_count: number
  continuers_count: number
  eligible_count: number
  entered_pct: number
  dropped_pct: number
  continuers_pct: number
  net_pct_us: number
  net_pct_us_signed: number
  churn_pct: number
  churn_pct_signed: number
}

export interface ScreenerBreadthFlowList {
  items: ScreenerBreadthFlowItem[]
  total_count: number
  page: number
  page_size: number
}

// ----- Screener setup tags (Rankings) -----
export type SetupBias = 'bullish' | 'bearish'
export type SetupNetBias = SetupBias | 'neutral'
export type SetupStrength = 'weak' | 'medium' | 'strong'

export interface SetupChip {
  label: string
  slug?: string | null
  interactive: boolean
  bias: SetupBias
  streak_days: number
  weight_3d: number
}

export interface SetupDeveloping {
  streak_days: number
  labels: string[]
  extra_count: number
}

export interface SetupSummaryItem {
  as_of_date: string
  symbol: string
  bullish: SetupChip[]
  bullish_extra_count: number
  bullish_developing: SetupDeveloping
  bearish: SetupChip[]
  bearish_extra_count: number
  bearish_developing: SetupDeveloping
  bullish_weight_3d: number
  bearish_weight_3d: number
  net_score_3d: number
  net_bias: SetupNetBias
  net_strength: SetupStrength
}

export interface SetupSummaryResponse {
  items: SetupSummaryItem[]
}

export interface SetupHit {
  as_of_date: string
  bucket: string
  bucket_slug?: string | null
  bucket_interactive: boolean
  bias: SetupBias
  style?: string | null
  source: string
  rank_value?: number | null
  weight: number
  style_weight: number
  source_weight: number
}

export interface SetupHitsDay {
  as_of_date: string
  hits: SetupHit[]
}

export interface SetupSymbolResponse {
  summary: SetupSummaryItem
  days: SetupHitsDay[]
  focus_slug?: string | null
}

// ----- Regime types -----
export interface RegimeCoverage {
  valid_points: number
  total_points: number
  has_signal: boolean
  warning?: string | null
}

export interface RegimeLatest {
  as_of_date: string
  risk_on_core: number
  risk_off_core: number
  regime_raw: number
  ema10: number
  ema50: number
  regime_label: string
  regime_index: number
  participation?: number | null
  effective_weights?: { canonical_name: string; effective_weight: number; base_weight?: number | null; g_factor?: number | null }[]
  has_signal?: boolean
  coverage_warning?: string | null
}

export interface RegimeSeriesItem extends RegimeLatest {}
export interface RegimeSeriesList {
  items: RegimeSeriesItem[]
  total_count: number
  page: number
  page_size: number
  coverage?: RegimeCoverage
}

export interface RegimeRulesLatest {
  as_of_date: string
  label: 'Trend' | 'Chop' | 'Risk-Off' | string
  tags: string[]
  config_version: string
  rs: number
  rs_smooth: number
  tt: number
  mrp: number
  rop: number
  dt: number
  mb: number
  bb: number
  mri: number
  db: number
  ps: number
  tb: number
}

export interface RegimeRulesSeriesItem extends RegimeRulesLatest {}
export interface RegimeRulesSeriesList {
  items: RegimeRulesSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

// ----- Price history types -----
export interface PriceHistoryItem {
  symbol: string
  company_name?: string
  price_date: string
  open_px?: number
  high_px?: number
  low_px?: number
  close_px?: number
  adj_close_px?: number
  volume?: number
}

export interface PriceHistoryList {
  items: PriceHistoryItem[]
  normalized?: boolean
  index_base?: number
  total_count: number
  page: number
  page_size: number
}

export interface LatestAdjItem {
  symbol: string
  company_name?: string
  price_date: string
  close_px?: number
  adj_close_px?: number
}

export interface LatestAdjList {
  items: LatestAdjItem[]
  total_count: number
  page: number
  page_size: number
}

export interface LivePrice {
  symbol: string
  bid?: number
  ask?: number
  last?: number
  close?: number
  change_pct?: number
  account?: string
  is_realtime?: boolean
  raw?: Record<string, unknown>
}

// ----- Technical indicators (per-stock) -----
export interface TechnicalsSnapshot {
  as_of_date: string
  symbol: string
  company_name?: string
  sma20?: number | null
  sma50?: number | null
  sma200?: number | null
  ema12?: number | null
  ema26?: number | null
  rsi14?: number | null
  atr14?: number | null
  bb_upper?: number | null
  bb_middle?: number | null
  bb_lower?: number | null
  macd?: number | null
  macd_signal?: number | null
  macd_hist?: number | null
  ret_5d?: number | null
  ret_20d?: number | null
  ret_60d?: number | null
  ret_120d?: number | null
  vol_z20?: number | null
  dist_52w_high?: number | null
}

export interface TechnicalsSeriesPoint {
  date: string
  value: number | null
}

export interface TechnicalsSeriesResponse {
  symbol: string
  series: Record<string, TechnicalsSeriesPoint[]>
}

// ----- Fundamentals (per-stock) -----
export interface FundamentalMetricItem {
  metric_code: string
  metric_name: string
  stmt_code: string
  default_unit?: string | null
  value?: number | null
  as_of_date?: string | null
  fiscal_year?: number | null
  fiscal_period?: string | null
  ttm_flag?: boolean | null
  source_name?: string | null
  source_version?: string | null
}

export interface FundamentalsSnapshot {
  symbol: string
  latest_as_of_date?: string | null
  latest_source_name?: string | null
  latest_source_version?: string | null
  sources?: string[]
  metrics: FundamentalMetricItem[]
  redacted?: boolean
  redaction_reason?: string | null
}

// ----- Macro / risk indicators -----
export type EmptyResponse = { status: 'empty' }

export interface MacroLiquidityLatest {
  as_of_date: string
  regime?: string | null
  rrp_change_mn?: number | null
  tga_change_mn?: number | null
  rrp_value_bil?: number | null
  tga_value_bil?: number | null
  on_rrp?: { as_of_date?: string | null; value?: number | null }
  tga?: { as_of_date?: string | null; value?: number | null }
}

export interface MacroSeriesItem {
  as_of_date: string
  value: number | null
}

export interface MacroLiquiditySeriesResponse {
  series: 'on_rrp' | 'tga'
  items: MacroSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export interface MacroTipsRealYieldSeriesResponse {
  series: 'tips10y'
  items: MacroSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export type MacroNetLiquidityLatestResponse =
  | EmptyResponse
  | {
      as_of_date: string
      net_liquidity_mn: number | null
      net_liquidity_trn: number | null
      delta_4w_mn: number | null
      delta_13w_mn: number | null
      delta_4w_trn: number | null
      delta_13w_trn: number | null
      delta_4w_z: number | null
      delta_13w_z: number | null
      components?: {
        walcl?: { series_code: string; value_mn: number | null }
        tga?: { series_code: string; value_mn: number | null }
        on_rrp?: { series_code: string; value_mn: number | null }
      }
    }

export interface MacroNetLiquiditySeriesItem {
  as_of_date: string
  walcl_mn: number | null
  tga_mn: number | null
  on_rrp_mn: number | null
  net_liquidity_mn: number | null
  net_liquidity_trn: number | null
}

export interface MacroNetLiquiditySeriesResponse {
  items: MacroNetLiquiditySeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export interface FedBalanceSheetLatestResponse {
  as_of_date: string
  walcl_trn?: number | null
  wshosho_trn?: number | null
  treast_trn?: number | null
  mbst_trn?: number | null
  wshosho_share_of_walcl?: number | null
  treast_share_of_wshosho?: number | null
  mbst_share_of_wshosho?: number | null
  walcl?: { as_of_date?: string | null; value?: number | null }
  wshosho?: { as_of_date?: string | null; value?: number | null }
  treast?: { as_of_date?: string | null; value?: number | null }
  mbst?: { as_of_date?: string | null; value?: number | null }
}

export interface FedBalanceSheetSeriesResponse {
  series: 'walcl' | 'wshosho' | 'treast' | 'mbst'
  items: MacroSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export type TreasuryLatestResponse =
  | EmptyResponse
  | {
      as_of_date: string
      rates: Record<string, { as_of_date: string | null; rate_pct: number | null }>
      curve?: { slope_2s10s_pct: number | null; slope_2s10s_bp: number | null }
    }

export interface TreasurySeriesItem {
  as_of_date: string
  rate_pct: number | null
}

export interface TreasurySeriesResponse {
  tenor: '1Y' | '2Y' | '5Y' | '10Y' | '20Y'
  items: TreasurySeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export type HyStressLatestResponse =
  | EmptyResponse
  | {
      as_of_date: string
      benchmark_name: string
      hy_stress_raw: number | null
      hy_stress_ma: number | null
      hy_stress_z: number | null
      label: 'risk_on' | 'neutral' | 'risk_off' | 'not enough data' | string
    }

export interface HyStressSeriesItem {
  as_of_date: string
  benchmark_name: string
  hy_stress_raw: number | null
  hy_stress_ma: number | null
  hy_stress_z: number | null
  label: string
}

export interface HyStressSeriesResponse {
  items: HyStressSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export interface FraOisLatestItem {
  as_of_date: string
  start_months: number
  end_months: number
  fra_source: string
  fra_rate: number | null
  ois_forward: number | null
  spread_bp: number | null
  fra_ois_z: number | null
  regime: 'easy' | 'normal' | 'stressed' | 'crisis' | 'not_enough_data' | string
}

export type FraOisLatestResponse = EmptyResponse | FraOisLatestItem[]

export interface FraOisSeriesItem extends FraOisLatestItem {}

export interface FraOisSeriesResponse {
  items: FraOisSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export type VolRegimeResponse =
  | EmptyResponse
  | {
      underlying_symbol: string
      as_of_date: string
      vix_1d: number | null
      vix_9d: number | null
      vix_1m: number | null
      vix_3m: number | null
      vix_6m: number | null
      vix_1y: number | null
      curve_slope: number | null
      num_inversions: number | null
      is_contango: boolean | null
      is_contango_full: boolean | null
      is_backwardation_front: boolean | null
      is_backwardation_short: boolean | null
      regime: string | null
      risk_flag: number | null
      rv_30d_var: number | null
      iv_30d_var: number | null
      vrp_30d: number | null
      vrp_regime: string | null
      vrp_state: string | null
      vol_state: string | null
      ratio_1m_3m?: number | null
      ratio_1m_6m?: number | null
    }

export type UpcomingEarningsItem = {
  symbol: string
  company_name?: string | null
  earnings_date: string
  earnings_time?: string | null
  earnings_source?: string | null
  market_cap?: number | null
}

export type UpcomingEarningsResponse = {
  as_of: string
  window_days: number
  min_market_cap: number
  items: UpcomingEarningsItem[]
}

export type NowcastLabel = 'risk_on' | 'neutral' | 'risk_off'

export type NowcastPillarKey = 'liquidity' | 'vol_tail' | 'funding' | 'credit' | 'rates_usd' | 'breadth' | 'flows'

export type NowcastPillarCommon = {
  title: string
  tier: number
  score: number | null
  data_as_of_date: string | null
}

export type NowcastLiquidityDetails = {
  regime_label: string | null
  rrp_value_bil: number | null
  tga_value_bil: number | null
  rrp_change_mn: number | null
  tga_change_mn: number | null
  label_risk_off: number | null
  net_liquidity_trn: number | null
  delta_4w_trn: number | null
  delta_13w_trn: number | null
  delta_4w_z: number | null
  delta_13w_z: number | null
  netliq_risk_off: number | null
}

export type NowcastVolTailDetails = {
  vix_1m: number | null
  curve_slope: number | null
  regime: string | null
  risk_flag: number | null
  term_risk_off: number | null
  skew: number | null
  skew_z252: number | null
  skew_z756: number | null
  skew_z: number | null
  skew_risk_off: number | null
}

export type NowcastFundingDetails = {
  spread_bp: number | null
  fra_ois_z: number | null
}

export type NowcastCreditDetails = {
  hy_stress_raw: number | null
  hy_stress_ma: number | null
  hy_stress_z: number | null
  benchmark_name: string | null
}

export type NowcastRatesUsdDetails = {
  usdx: number | null
  usdx_z: number | null
  usdx_risk_off: number | null
  slope_2s10s: number | null
  slope_2s10s_z: number | null
  curve_risk_off: number | null
  tips_delta20: number | null
  tips_delta20_z: number | null
  tips_risk_off: number | null
  y10: number | null
  y10_delta5: number | null
  y10_delta20: number | null
  y10_shock_bp: number | null
  y10_shock_z: number | null
  rates_shock_risk_off: number | null
}

export type NowcastBreadthDetails = {
  target_exposure: number | null
}

export type NowcastFlowsDetails = {
  appetite: number | null
  appetite_z: number | null
  risk_off: number | null
}

export type NowcastPillar =
  | ({ pillar_key: 'liquidity'; details: NowcastLiquidityDetails } & NowcastPillarCommon)
  | ({ pillar_key: 'vol_tail'; details: NowcastVolTailDetails } & NowcastPillarCommon)
  | ({ pillar_key: 'funding'; details: NowcastFundingDetails } & NowcastPillarCommon)
  | ({ pillar_key: 'credit'; details: NowcastCreditDetails } & NowcastPillarCommon)
  | ({ pillar_key: 'rates_usd'; details: NowcastRatesUsdDetails } & NowcastPillarCommon)
  | ({ pillar_key: 'breadth'; details: NowcastBreadthDetails } & NowcastPillarCommon)
  | ({ pillar_key: 'flows'; details: NowcastFlowsDetails } & NowcastPillarCommon)

export type NowcastDriver = NowcastPillar & {
  weight: number
  impact: number
}

export type NowcastAlert = NowcastPillar & {
  severity: 'risk_off' | 'risk_on'
}

export type NowcastMapTrailPoint = {
  as_of_date: string | null
  liquidity_ease: number | null
  stress_score: number | null
  overall_risk_off: number | null
}

export type NowcastLatestResponse =
  | EmptyResponse
  | {
      model_version: string
      as_of_date: string | null
      overall_risk_off_score: number | null
      nowcast_label: NowcastLabel | null
      confidence: number | null
      coverage: number | null
      delta_1d: number | null
      delta_5d: number | null
      label_1d_ago: NowcastLabel | null
      label_5d_ago: NowcastLabel | null
      cross_asset_stress_score: number | null
      cross_asset_label: NowcastLabel | null
      booster_applied: boolean
      booster_amount: number | null
      spx_tlt_corr60: number | null
      spx_ret20: number | null
      tlt_ret20: number | null
      pillars: NowcastPillar[]
      drivers: NowcastDriver[]
      alerts: NowcastAlert[]
      map_trail: NowcastMapTrailPoint[]
    }

export interface BreadthLatestResponse {
  as_of_date: string | null
  nyse: Record<string, number | null>
  spx: Record<string, number | null>
  ndx: Record<string, number | null>
}

export interface BreadthSeriesItem {
  as_of_date: string
  value: number | null
  label?: string | null
}

export interface BreadthSeriesResponse {
  items: BreadthSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export interface MacroPutCallLatestResponse {
  as_of_date: string | null
  total: { as_of_date: string | null; value: number | null }
  equity: { as_of_date: string | null; value: number | null }
  spx: { as_of_date: string | null; value: number | null }
  index: { as_of_date: string | null; value: number | null }
}

export interface MacroPutCallSeriesItem {
  as_of_date: string
  value: number | null
}

export interface MacroPutCallSeriesResponse {
  series: 'total' | 'equity' | 'spx' | 'index'
  items: MacroPutCallSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export interface MoneyFlowSectorItem {
  sector: string
  sector_etf?: string | null
  n_stocks: number
  avg_score: number | null
}

export interface MoneyFlowSectorsResponse {
  as_of_date: string
  sectors: MoneyFlowSectorItem[]
}

export interface MoneyFlowSectorSeriesItem {
  date: string
  sector: string
  sector_etf?: string | null
  avg_score: number | null
  n_stocks: number
}

export interface MoneyFlowSectorSeriesResponse {
  as_of_date: string
  trading_days: number
  series: MoneyFlowSectorSeriesItem[]
}

export type BenchmarkLatestResponse =
  | EmptyResponse
  | {
      as_of_date: string
      benchmark_name: string
      currency_code: string
      description?: string | null
      close_px: number | null
      total_return_factor: number | null
    }

export interface BenchmarkSeriesItem {
  as_of_date: string
  benchmark_name: string
  close_px: number | null
  total_return_factor: number | null
}

export interface BenchmarkSeriesResponse {
  items: BenchmarkSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export type FxLatestResponse =
  | EmptyResponse
  | {
      as_of_date: string | null
      pairs: Record<
        string,
        {
          pair: string
          from_ccy: string
          to_ccy: string
          as_of_date: string | null
          mid_px: number | null
        }
      >
    }

export interface FxSeriesItem {
  as_of_date: string
  mid_px: number | null
}

export interface FxSeriesResponse {
  pair: string
  from_ccy: string
  to_ccy: string
  items: FxSeriesItem[]
  total_count: number
  page: number
  page_size: number
}

export interface MarketStructureRow {
  as_of_date: string
  trend_raw?: number
  rv20_ann?: number
  corr_pca1_share?: number
  disp_cs_mad?: number
  trend_z?: number
  rv20_z?: number
  corr_z?: number
  disp_z?: number
  label?: 'CalmUptrend' | 'FragileUptrend' | 'Choppy' | 'Risk-Off' | 'Neutral'
}

// ----- Client -----
export const api = {
  // grading
  async getStockGrades(params: {
    limit?: number
    skip?: number
    min_grade?: string
    max_grade?: string
    sector?: string
    sort_by?: string
    sort_order?: 'asc' | 'desc'
    search?: string
    tracked_only?: boolean
    as_of?: string
    has_setup?: boolean
    setup_styles?: string[]
    setup_bias?: 'both' | SetupBias
    setup_logic?: 'any' | 'all'
  }): Promise<GradeLeaderboard> {
    const base = buildUrl('/grading/grades')
    const qs = new URLSearchParams()
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.min_grade) qs.set('min_grade', params.min_grade)
    if (params.max_grade) qs.set('max_grade', params.max_grade)
    if (params.sector) qs.set('sector', params.sector)
    if (params.sort_by) qs.set('sort_by', params.sort_by)
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    if (params.search) qs.set('search', params.search)
    if (params.tracked_only !== undefined) qs.set('tracked_only', String(params.tracked_only))
    if (params.as_of) qs.set('as_of', params.as_of)
    if (params.has_setup !== undefined) qs.set('has_setup', String(params.has_setup))
    if (params.setup_bias) qs.set('setup_bias', params.setup_bias)
    if (params.setup_logic) qs.set('setup_logic', params.setup_logic)
    if (params.setup_styles && params.setup_styles.length) {
      params.setup_styles.forEach((s) => {
        if (s) qs.append('setup_styles', s)
      })
    }
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },
  async getGradesBatch(
    symbols: string[],
    options?: { baseUrl?: string; fetchInit?: RequestInit }
  ): Promise<{ items: PeerGradeItem[] }> {
    if (!symbols || symbols.length === 0) return { items: [] }
    const qs = new URLSearchParams()
    symbols.forEach((s) => {
      const sym = (s || '').trim().toUpperCase()
      if (sym) qs.append('symbols', sym)
    })
    const normalizedBase = options?.baseUrl ? options.baseUrl.replace(/\/$/, '') : null
    const cleanedBase = normalizedBase ? normalizedBase.replace(/\/api\/v1$/, '') : null
    const serverBase = cleanedBase
      ? `${cleanedBase}${BACKEND_PREFIX}/grading/grades/batch`
      : buildUrl('/grading/grades/batch')
    const url = qs.toString() ? `${serverBase}?${qs.toString()}` : serverBase

    if (typeof window === 'undefined') {
      const res = await fetch(url, options?.fetchInit)
      if (!res.ok) {
        if (res.status === 404 || res.status === 400) {
          return { items: [] }
        }
        throw new Error(`Failed to fetch grades batch: ${res.status}`)
      }
      return (await res.json()) as { items: PeerGradeItem[] }
    }

    const { data } = await axios.get(url)
    return data
  },
  async listSectors(): Promise<string[]> {
    const { data } = await axios.get(buildUrl('/grading/sectors'))
    return data
  },

  async getPipelineHealth(): Promise<PipelineHealth> {
    const { data } = await axios.get(buildUrl('/pipeline/health'))
    return data
  },

  async getModelWeights(): Promise<ModelWeights> {
    const { data } = await axios.get(buildUrl('/grading/weights'))
    return data
  },

  async getAssetDetail(symbol: string): Promise<AssetDetail> {
    const normalized = (symbol || '').trim().toUpperCase()
    const { data } = await axios.get(buildUrl(`/grading/asset/${encodeURIComponent(normalized)}`))
    return data
  },

  async getAiAnalysis(params: { page?: number; page_size?: number; symbol?: string; date_from?: string; date_to?: string }): Promise<AiAnalysisList> {
    const { data } = await axios.get(buildUrl('/ai-analysis'), { params })
    return data
  },

  async listAiAnalyses(params: { symbol?: string; date_from?: string; date_to?: string; skip?: number; limit?: number; sort_order?: 'asc' | 'desc'; latest_only_per_symbol?: boolean }): Promise<AiAnalysisList> {
    const { data } = await axios.get(buildUrl('/ai-analysis'), { params })
    return data
  },

  async listAiAnalysesLatest(params: {
    symbol?: string
    date_from?: string
    date_to?: string
    ratings?: string[]
    confidences?: string[]
    sectors?: string[]
    nearest_scenarios?: string[]
    nearest_distance_pct_max?: number
    delta_base_pct_min?: number
    delta_base_pct_max?: number
    base_probability_pct_min?: number
    skip?: number
    limit?: number
    sort_by?: 'date' | 'symbol'
    sort_order?: 'asc' | 'desc'
    include_proximity?: boolean
  }): Promise<AiAnalysisList> {
    // Always go through the Next.js BFF so we get tag-based caching and revalidate.
    // Note: Axios default array serialization uses bracket syntax (e.g. ratings[]=buy),
    // but FastAPI expects repeated keys (e.g. ratings=buy&ratings=sell).
    const qs = new URLSearchParams()
    if (params.symbol) qs.set('symbol', params.symbol)
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    params.ratings?.forEach((v) => qs.append('ratings', v))
    params.confidences?.forEach((v) => qs.append('confidences', v))
    params.sectors?.forEach((v) => qs.append('sectors', v))
    params.nearest_scenarios?.forEach((v) => qs.append('nearest_scenarios', v))
    if (params.nearest_distance_pct_max !== undefined) qs.set('nearest_distance_pct_max', String(params.nearest_distance_pct_max))
    if (params.delta_base_pct_min !== undefined) qs.set('delta_base_pct_min', String(params.delta_base_pct_min))
    if (params.delta_base_pct_max !== undefined) qs.set('delta_base_pct_max', String(params.delta_base_pct_max))
    if (params.base_probability_pct_min !== undefined) qs.set('base_probability_pct_min', String(params.base_probability_pct_min))
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.sort_by) qs.set('sort_by', params.sort_by)
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    if (params.include_proximity !== undefined) qs.set('include_proximity', String(params.include_proximity))

    const base = buildUrl('/ai-analysis/latest')
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async getAiAnalysisDetail(analysisId: string, include_proximity = false): Promise<AiAnalysisItem> {
    const { data } = await axios.get(buildUrl(`/ai-analysis/id/${encodeURIComponent(analysisId)}`), { params: include_proximity ? { include_proximity: true } : undefined })
    return data
  },

  async getAiAnalysisById(analysisId: string, include_proximity = false): Promise<AiAnalysisItem> {
    return this.getAiAnalysisDetail(analysisId, include_proximity)
  },

  async getLatestAiAnalysis(symbol: string): Promise<AiAnalysisItem | null> {
    const res = await this.listAiAnalyses({ symbol, limit: 1 })
    return res.items[0] || null
  },

  async getAiPreviews(symbols: string[]): Promise<Record<string, AiPreview>> {
    if (!symbols || symbols.length === 0) return {}
    const params = new URLSearchParams()
    symbols.forEach(s => params.append('symbols', s))
    const { data } = await axios.get(buildUrl(`/ai-analysis/preview?${params.toString()}`))
    return data
  },

  async enqueueSentimentAnalysis(params: {
    symbol: string
    priority?: number
    force?: boolean
    eventId?: string
    title?: string
    url?: string
    rawId?: string
  }): Promise<{ ok: boolean; [key: string]: any }> {
    if (!params?.symbol) {
      throw new Error('symbol is required')
    }
    const payload = {
      symbol: params.symbol,
      priority: params.priority,
      force: params.force,
      eventId: params.eventId,
      title: params.title,
      url: params.url,
      rawId: params.rawId,
    }
    const { data } = await axios.post(buildUrl('/admin/news/queue/enqueue'), payload)
    return data
  },

  async getScreenerConsensus(params: { page?: number; page_size?: number }): Promise<ScreenerConsensusList> {
    const { data } = await axios.get(buildUrl('/screener/consensus'), { params })
    return data
  },

  async listScreenerConsensus(params: {
    symbol?: string
    styles?: string[]
    sources?: string[]
    style_logic?: 'any' | 'all'
    source_logic?: 'any' | 'all'
    appearances_min?: number
    styles_min?: number
    skip?: number
    limit?: number
    sort_by?: string
    sort_order?: 'asc' | 'desc'
    position_side?: 'long' | 'short'
  }): Promise<ScreenerConsensusList> {
    const base = buildUrl('/screener/consensus')
    const qs = new URLSearchParams()
    if (params.symbol) qs.set('symbol', params.symbol)
    if (params.styles && params.styles.length) params.styles.forEach(s => qs.append('styles', s))
    if (params.sources && params.sources.length) params.sources.forEach(s => qs.append('sources', s))
    if (params.style_logic) qs.set('style_logic', params.style_logic)
    if (params.source_logic) qs.set('source_logic', params.source_logic)
    if (params.appearances_min !== undefined) qs.set('appearances_min', String(params.appearances_min))
    if (params.styles_min !== undefined) qs.set('styles_min', String(params.styles_min))
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.sort_by) qs.set('sort_by', params.sort_by)
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    if (params.position_side) qs.set('position_side', params.position_side)
    const url = `${base}?${qs.toString()}`
    const { data } = await axios.get(url)
    return data
  },

  // Note: direct styles/sources lists are unused; use meta endpoints below

  async listScreenerStylesMeta(params: { bias?: 'all' | 'bullish' | 'bearish' } = {}): Promise<OptionCount[]> {
    const base = buildUrl('/screener/styles/meta')
    const qs = new URLSearchParams()
    if (params.bias) qs.set('bias', params.bias)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async listScreenerSourcesMeta(params: { position_side?: 'long'|'short'; prefix?: string; styles?: string[] } = {}): Promise<OptionCount[]> {
    const base = buildUrl('/screener/sources/meta')
    const qs = new URLSearchParams()
    if (params.position_side) qs.set('position_side', params.position_side)
    if (params.prefix) qs.set('prefix', params.prefix)
    if (params.styles && params.styles.length) params.styles.forEach(s => qs.append('styles', s))
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async listScreenerChanges(params: {
    symbol?: string
    styles?: string[]
    sources?: string[]
    change_types?: ScreenerChangeType[]
    start_date?: string
    end_date?: string
    latest_only?: boolean
    skip?: number
    limit?: number
    sort_by?: string
    sort_order?: 'asc' | 'desc'
    position_side?: 'long' | 'short'
  } = {}): Promise<ScreenerChangeList> {
    const base = buildUrl('/screener/changes')
    const qs = new URLSearchParams()
    if (params.symbol) qs.set('symbol', params.symbol)
    params.styles?.forEach(s => qs.append('styles', s))
    params.sources?.forEach(s => qs.append('sources', s))
    params.change_types?.forEach(ct => qs.append('change_types', ct))
    if (params.start_date) qs.set('start_date', params.start_date)
    if (params.end_date) qs.set('end_date', params.end_date)
    if (params.latest_only !== undefined) qs.set('latest_only', String(params.latest_only))
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.sort_by) qs.set('sort_by', params.sort_by)
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    if (params.position_side) qs.set('position_side', params.position_side)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async listScreenerBreadth(params: {
    styles?: string[]
    start_date?: string
    end_date?: string
    skip?: number
    limit?: number
    sort_order?: 'asc' | 'desc'
    position_side?: 'long' | 'short'
  } = {}): Promise<ScreenerBreadthList> {
    const base = buildUrl('/screener/breadth')
    const qs = new URLSearchParams()
    params.styles?.forEach(s => qs.append('styles', s))
    if (params.start_date) qs.set('start_date', params.start_date)
    if (params.end_date) qs.set('end_date', params.end_date)
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    if (params.position_side) qs.set('position_side', params.position_side)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async listScreenerBreadthFlow(params: {
    styles?: string[]
    start_date?: string
    end_date?: string
    skip?: number
    limit?: number
    sort_order?: 'asc' | 'desc'
  } = {}): Promise<ScreenerBreadthFlowList> {
    const base = buildUrl('/screener/breadth/flow')
    const qs = new URLSearchParams()
    params.styles?.forEach(s => qs.append('styles', s))
    if (params.start_date) qs.set('start_date', params.start_date)
    if (params.end_date) qs.set('end_date', params.end_date)
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async getSetupSummaries(symbols: string[], params: { window_days?: number } = {}): Promise<SetupSummaryResponse> {
    if (!symbols || symbols.length === 0) return { items: [] }
    const qs = new URLSearchParams()
    symbols.forEach((s) => qs.append('symbols', s))
    if (params.window_days !== undefined) qs.set('window_days', String(params.window_days))
    const { data } = await axios.get(buildUrl(`/screener/setups/summary?${qs.toString()}`))
    return data
  },

  async getSetupSymbolView(params: { symbol: string; window_days?: number; focus_slug?: string }): Promise<SetupSymbolResponse> {
    if (!params?.symbol) throw new Error('symbol is required')
    const qs = new URLSearchParams()
    qs.set('symbol', params.symbol)
    if (params.window_days !== undefined) qs.set('window_days', String(params.window_days))
    if (params.focus_slug) qs.set('focus_slug', params.focus_slug)
    const { data } = await axios.get(buildUrl(`/screener/setups/symbol?${qs.toString()}`))
    return data
  },

  async getRegimeLatest(): Promise<RegimeLatest | EmptyResponse> {
    const { data } = await axios.get(buildUrl('/screener/regime/latest'))
    return data
  },

  async getRegimeSeries(params: { limit?: number; sort_order?: 'asc'|'desc' } = {}): Promise<RegimeSeriesList> {
    const base = buildUrl('/screener/regime/series')
    const qs = new URLSearchParams()
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async getRegimeRulesLatest(): Promise<RegimeRulesLatest | EmptyResponse> {
    const { data } = await axios.get(buildUrl('/screener/regime-rules/latest'))
    return data
  },

  async getRegimeRulesSeries(params: { start_date?: string; end_date?: string; limit?: number; skip?: number; sort_order?: 'asc'|'desc' } = {}): Promise<RegimeRulesSeriesList> {
    const base = buildUrl('/screener/regime-rules/series')
    const qs = new URLSearchParams()
    if (params.start_date) qs.set('start_date', params.start_date)
    if (params.end_date) qs.set('end_date', params.end_date)
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  // prices
  async getPriceHistory(params: { symbol: string; date_from?: string; date_to?: string; skip?: number; limit?: number }): Promise<PriceHistoryList> {
    if (!params?.symbol) throw new Error('symbol is required')
    const normalized = (params.symbol || '').trim().toUpperCase()
    const { data } = await axios.get(buildUrl('/prices/history'), { params: { ...params, symbol: normalized } })
    return data
  },

  async getLatestAdj(params: { symbol?: string; skip?: number; limit?: number; sort_by?: 'symbol'|'date'; sort_order?: 'asc'|'desc' } = {}): Promise<LatestAdjList> {
    const { data } = await axios.get(buildUrl('/prices/latest'), { params })
    return data
  },

  async getLivePrice(symbol: string, params: { account?: string; exchange?: string } = {}): Promise<LivePrice> {
    const normalized = (symbol || '').trim().toUpperCase()
    const encoded = encodeURIComponent(normalized)
    const { data } = await axios.get(buildUrl(`/prices/live/${encoded}`), { params })
    return data
  },

  // technical indicators (per-stock)
  async getTechnicalsLatest(symbol: string): Promise<TechnicalsSnapshot> {
    if (!symbol) throw new Error('symbol is required')
    const normalized = symbol.trim().toUpperCase()
    const { data } = await axios.get(buildUrl('/technicals/latest'), { params: { symbol: normalized } })
    return data
  },

  async getTechnicalsSeries(params: { symbol: string; indicators?: string[]; days?: number }): Promise<TechnicalsSeriesResponse> {
    if (!params?.symbol) throw new Error('symbol is required')
    const query: Record<string, any> = { symbol: params.symbol.trim().toUpperCase() }
    if (params.days !== undefined) query.days = params.days
    if (params.indicators && params.indicators.length) query.indicators = params.indicators.join(',')
    const { data } = await axios.get(buildUrl('/technicals/series'), { params: query })
    return data
  },

  // fundamentals (per-stock)
  async getFundamentalsLatest(params: { symbol: string; metrics?: string[] }): Promise<FundamentalsSnapshot> {
    if (!params?.symbol) throw new Error('symbol is required')
    const query: Record<string, any> = { symbol: params.symbol.trim().toUpperCase() }
    if (params.metrics && params.metrics.length) query.metrics = params.metrics.join(',')
    const { data } = await axios.get(buildUrl('/fundamentals/latest'), { params: query })
    return data
  },

  // macro / risk
  async getMacroLiquidityLatest(): Promise<MacroLiquidityLatest> {
    const { data } = await axios.get(buildUrl('/macro/liquidity/latest'))
    return data
  },

  async getMacroLiquiditySeries(params: {
    series: 'on_rrp' | 'tga'
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  }): Promise<MacroLiquiditySeriesResponse> {
    const { data } = await axios.get(buildUrl('/macro/liquidity/series'), { params })
    return data
  },

  async getMacroNetLiquidityLatest(params: { lookback_weeks?: number } = {}): Promise<MacroNetLiquidityLatestResponse> {
    const { data } = await axios.get(buildUrl('/macro/liquidity/net-liquidity/latest'), { params })
    return data
  },

  async getMacroNetLiquiditySeries(params: {
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  } = {}): Promise<MacroNetLiquiditySeriesResponse> {
    const { data } = await axios.get(buildUrl('/macro/liquidity/net-liquidity/series'), { params })
    return data
  },

  async getFedBalanceSheetLatest(): Promise<FedBalanceSheetLatestResponse> {
    const { data } = await axios.get(buildUrl('/macro/fed-balance-sheet/latest'))
    return data
  },

  async getFedBalanceSheetSeries(params: {
    series: 'walcl' | 'wshosho' | 'treast' | 'mbst'
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  }): Promise<FedBalanceSheetSeriesResponse> {
    const { data } = await axios.get(buildUrl('/macro/fed-balance-sheet/series'), { params })
    return data
  },

  async getMacroTipsRealYieldSeries(params: {
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  } = {}): Promise<MacroTipsRealYieldSeriesResponse> {
    const { data } = await axios.get(buildUrl('/macro/real-rates/tips10y/series'), { params })
    return data
  },

  async getTreasuryLatest(params: { tenors?: string } = {}): Promise<TreasuryLatestResponse> {
    const { data } = await axios.get(buildUrl('/rates/treasury/latest'), { params })
    return data
  },

  async getTreasurySeries(params: {
    tenor: 'O/N' | '1Y' | '2Y' | '5Y' | '10Y' | '20Y'
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  }): Promise<TreasurySeriesResponse> {
    const { data } = await axios.get(buildUrl('/rates/treasury/series'), { params })
    return data
  },

  async getHyStressLatest(params: { benchmark_name?: string } = {}): Promise<HyStressLatestResponse> {
    const { data } = await axios.get(buildUrl('/hy-stress/latest'), { params })
    return data
  },

  async getHyStressSeries(params: {
    benchmark_name?: string
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  } = {}): Promise<HyStressSeriesResponse> {
    const { data } = await axios.get(buildUrl('/hy-stress/series'), { params })
    return data
  },

  async getMacroPutCallLatest(): Promise<MacroPutCallLatestResponse> {
    const { data } = await axios.get(buildUrl('/macro/put-call/latest'))
    return data
  },

  async getMacroPutCallSeries(params: {
    series: 'total' | 'equity' | 'spx' | 'index'
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  }): Promise<MacroPutCallSeriesResponse> {
    const { data } = await axios.get(buildUrl('/macro/put-call/series'), { params })
    return data
  },

  async getFraOisLatest(params: {
    fra_source?: string
    start_months?: number
    end_months?: number
  } = {}): Promise<FraOisLatestResponse> {
    const { data } = await axios.get(buildUrl('/fra-ois/latest'), { params })
    return data
  },

  async getFraOisSeries(params: {
    fra_source?: string
    start_months?: number
    end_months?: number
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  } = {}): Promise<FraOisSeriesResponse> {
    const { data } = await axios.get(buildUrl('/fra-ois/series'), { params })
    return data
  },

  async getVolRegimeLatest(params: { underlying_symbol?: string } = {}): Promise<VolRegimeResponse> {
    const { data } = await axios.get(buildUrl('/vol-regime'), { params })
    return data
  },

  async getNowcastLatest(params: { model_version?: string; trail_days?: number } = {}): Promise<NowcastLatestResponse> {
    const { data } = await axios.get(buildUrl('/nowcast/latest'), { params })
    return data
  },

  async getUpcomingEarnings(params: { days?: number; min_market_cap?: number; limit?: number } = {}): Promise<UpcomingEarningsResponse> {
    const { data } = await axios.get(buildUrl('/earnings/upcoming'), { params })
    return data
  },

  async getBreadthLatest(): Promise<BreadthLatestResponse> {
    const { data } = await axios.get(buildUrl('/breadth/latest'))
    return data
  },

  async getBreadthSeries(params: {
    universe: 'SPX' | 'NDX' | 'NYSE'
    indicator: string
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  }): Promise<BreadthSeriesResponse> {
    const { data } = await axios.get(buildUrl('/breadth/series'), { params })
    return data
  },

  async getMoneyFlowSectors(): Promise<MoneyFlowSectorsResponse> {
    const { data } = await axios.get(buildUrl('/money-flow/sectors'))
    return data
  },

  async getMoneyFlowSectorSeries(params: { days?: number; sector?: string } = {}): Promise<MoneyFlowSectorSeriesResponse> {
    const { data } = await axios.get(buildUrl('/money-flow/sectors/series'), { params })
    return data
  },

  async getBenchmarkLatest(params: { benchmark_name: string }): Promise<BenchmarkLatestResponse> {
    if (!params?.benchmark_name) throw new Error('benchmark_name is required')
    const { data } = await axios.get(buildUrl('/benchmarks/latest'), { params })
    return data
  },

  async getBenchmarkSeries(params: {
    benchmark_name: string
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  }): Promise<BenchmarkSeriesResponse> {
    if (!params?.benchmark_name) throw new Error('benchmark_name is required')
    const { data } = await axios.get(buildUrl('/benchmarks/series'), { params })
    return data
  },

  async getFxLatest(params: { pairs: string }): Promise<FxLatestResponse> {
    if (!params?.pairs) throw new Error('pairs is required')
    const { data } = await axios.get(buildUrl('/fx/latest'), { params })
    return data
  },

  async getFxSeries(params: {
    pair: string
    start_date?: string
    end_date?: string
    sort_order?: 'asc' | 'desc'
    limit?: number
    skip?: number
  }): Promise<FxSeriesResponse> {
    if (!params?.pair) throw new Error('pair is required')
    const { data } = await axios.get(buildUrl('/fx/series'), { params })
    return data
  },

  // rank-regime (Momentum↔Value)
  async getRankRegimeLatest(): Promise<{
    as_of_date: string
    universe_size: number
    momentum_breadth: number
    value_breadth: number
    breadth_spread: number
    val_to_mom_raw: number
    mom_to_val_raw: number
    top_bucket_turnover: number
    val_to_mom_norm: number
    mom_to_val_norm: number
    fri_z: number
    fri_log: number
    tenure_m_median_days?: number | null
    tenure_v_median_days?: number | null
    hazard_m: number
    hazard_v: number
    factor_skew_mean: number
    dispersion_m_std?: number | null
    dispersion_v_std?: number | null
    regime_label: 'momentum_led' | 'value_led' | 'transition' | 'stress'
    regime_confidence?: number | null
  }> {
    const { data } = await axios.get(buildUrl('/signals/rank-regime'))
    return data
  },

  async getRankRegimeHistory(params: { days?: number; sort_order?: 'asc'|'desc' } = {}): Promise<{ items: Array<{
    as_of_date: string
    fri_z: number
    momentum_breadth: number
    value_breadth: number
    breadth_spread: number
    tenure_m_median_days?: number | null
  }>; total_count: number }> {
    const base = buildUrl('/signals/rank-regime/history')
    const qs = new URLSearchParams()
    if (params.days !== undefined) qs.set('days', String(params.days))
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },

  async getMarketStructureLatest(): Promise<MarketStructureRow> {
    const { data } = await axios.get(buildUrl('/market-structure/latest'))
    return data
  },

  async getMarketStructureSeries(params: { start_date?: string; end_date?: string; limit?: number; skip?: number; sort_order?: 'asc' | 'desc' } = {}): Promise<{
    items: MarketStructureRow[]
    total_count: number
    page: number
    page_size: number
  }> {
    const base = buildUrl('/market-structure/series')
    const qs = new URLSearchParams()
    if (params.start_date) qs.set('start_date', params.start_date)
    if (params.end_date) qs.set('end_date', params.end_date)
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.skip !== undefined) qs.set('skip', String(params.skip))
    if (params.sort_order) qs.set('sort_order', params.sort_order)
    const url = qs.toString() ? `${base}?${qs.toString()}` : base
    const { data } = await axios.get(url)
    return data
  },
}
