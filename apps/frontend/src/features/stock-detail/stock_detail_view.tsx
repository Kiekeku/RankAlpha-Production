import type { ReactNode } from 'react'

import Link from 'next/link'
import { notFound } from 'next/navigation'
import { Badge } from '@/components/ui/badge'
import { CalendarIcon, TrendingUpIcon, BarChart3Icon, ChevronDownIcon, FilterIcon } from 'lucide-react'
import { formatEasternDate } from '@/lib/date'
import { formatScore } from '@/lib/utils'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { TooltipCopyButton } from '@/components/tooltip_copy'
import { StockPriceHistoryCard } from '@/features/stock-detail/stock_price_history_card'
import { TechnicalIndicatorTiles } from '@/features/stock-detail/technical_indicator_tiles'
import { getInternalApiBase } from '@/app/api/_utils/upstream'
import { RecentTickerTracker } from '@/components/recent-ticker-tracker'
import { TickerHeader } from '@/components/ticker/ticker-header'
import { TickerFundamentalsDetails } from '@/components/ticker/ticker-fundamentals-details'
import { TickerFreshnessBar } from '@/components/ticker/ticker-freshness-bar'
import { TickerSectionNav } from '@/components/ticker/ticker-section-nav'
import { DataFooter } from '@/components/data-footer'
import type { DataFreshnessItem } from '@/components/data/data-freshness-bar'
import { CompareCheckbox } from '@/components/compare/compare_checkbox'
import { TechnicalReadout } from '@/features/stock-detail/technical_readout'
import { AiTargetSpread } from '@/features/stock-detail/ai_target_spread'
import {
  formatNumberValue,
  formatSignedPercent,
  formatUsd,
  formatUsdCompactFromMillions,
} from '@/features/stock-detail/stock_detail_format'
import { UI_TERMS, formatSetupHitsLabel, formatSetupTag } from '@/lib/ui_terms'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

type AssetDetail = {
  symbol: string
  company_name?: string
  sector?: string
  exchange?: string
  target_price?: number | null
  next_earnings_date?: string | null
  next_earnings_time?: string | null
  next_earnings_source?: string | null
  current_grade: {
    date: string
    momentum_score?: number
    value_score?: number
    sentiment_score?: number
    overall_grade: string
    grade_explanation: string
    confidence: string
  }
  score_history: { date: string; score_type: string; score: number }[]
  recent_news: { headline: string; analysis_date?: string; type: string }[]
  ai_analysis?: any
}

type TechnicalsSnapshot = {
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

type LatestAdjList = {
  items?: Array<{
    adj_close_px?: number | null
    close_px?: number | null
  }>
}

type TechnicalsSeriesPoint = { date: string; value: number | null }
type TechnicalsSeriesResponse = { symbol: string; series: Record<string, TechnicalsSeriesPoint[]> }

type FundamentalMetricItem = {
  metric_code: string
  value?: number | null
  source_name?: string | null
  source_version?: string | null
}
type FundamentalsSnapshot = {
  symbol: string
  latest_as_of_date?: string | null
  latest_source_name?: string | null
  latest_source_version?: string | null
  sources?: string[]
  metrics: FundamentalMetricItem[]
  redacted?: boolean
  redaction_reason?: string | null
}

type SetupHit = {
  as_of_date: string
  bucket: string
  bias: 'bullish' | 'bearish'
  style?: string | null
  source: string
  weight?: number | null
}

type SetupHitsDay = {
  as_of_date: string
  hits: SetupHit[]
}

type SetupSymbolResponse = {
  summary: any
  days: SetupHitsDay[]
  focus_slug?: string | null
}

type PeerGradesResponse = {
  items: Array<{ symbol: string; overall_grade: string }>
}

type SimilarPeerItem = {
  symbol: string
  company_name?: string | null
  sector?: string | null
  market_cap?: number | null
  market_cap_diff_pct?: number | null
}

type SimilarPeersResponse = {
  symbol: string
  sector?: string | null
  market_cap?: number | null
  items: SimilarPeerItem[]
}

type ModelWeights = {
  as_of_date: string
  method?: string
  w_momentum: number
  w_value: number
  w_sentiment: number
  source?: 'db' | 'default'
}

const SLOW_FETCH_MS = 750

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T | null> {
  const started = Date.now()
  try {
    const res = await fetch(url, init)
    if (!res.ok) return null
    try {
      return (await res.json()) as T
    } catch {
      return null
    }
  } catch {
    return null
  } finally {
    if (process.env.NODE_ENV !== 'production') {
      const elapsed = Date.now() - started
      if (elapsed > SLOW_FETCH_MS) {
        console.warn(`[ticker] slow fetch ${elapsed}ms ${url}`)
      }
    }
  }
}

function prefetchJson(url: string, init?: RequestInit) {
  void fetch(url, init)
    .then((res) => res.arrayBuffer().catch(() => null))
    .catch(() => null)
}

function formatSignedDelta(value?: number | null, digits = 1) {
  if (value == null || !Number.isFinite(value)) return '-'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}`
}

function formatEarningsTime(value?: string | null) {
  const raw = (value || '').trim()
  if (!raw) return null
  const normalized = raw.toLowerCase()
  if (normalized === 'bmo') return 'BMO'
  if (normalized === 'amc') return 'AMC'
  if (normalized === 'dmh') return 'DMH'
  return raw.toUpperCase()
}

function scoreSeriesDelta(
  history: Array<{ date: string; score_type: string; score: number }>,
  kind: 'momentum' | 'value' | 'sentiment',
  lookbackDays: number,
) {
  const points = history
    .map((h) => ({
      t: Date.parse(h.date),
      kind: (h.score_type || '').toLowerCase(),
      v: Number(h.score),
    }))
    .filter((p) => Number.isFinite(p.t) && p.kind.includes(kind) && Number.isFinite(p.v))
    .sort((a, b) => a.t - b.t)

  if (points.length < 2) return null
  const latest = points[points.length - 1]
  const target = latest.t - lookbackDays * 24 * 60 * 60 * 1000
  for (let i = points.length - 2; i >= 0; i--) {
    if (points[i].t <= target) return latest.v - points[i].v
  }
  return null
}

function effectiveWeights(weights: ModelWeights | null, scores: { momentum?: number | null; value?: number | null; sentiment?: number | null }) {
  const w = weights
    ? { m: weights.w_momentum, v: weights.w_value, s: weights.w_sentiment }
    : { m: 0.4, v: 0.4, s: 0.2 }
  const present = {
    m: typeof scores.momentum === 'number' && Number.isFinite(scores.momentum),
    v: typeof scores.value === 'number' && Number.isFinite(scores.value),
    s: typeof scores.sentiment === 'number' && Number.isFinite(scores.sentiment),
  }
  const total = (present.m ? w.m : 0) + (present.v ? w.v : 0) + (present.s ? w.s : 0)
  if (!total) return { m: 0, v: 0, s: 0 }
  return {
    m: present.m ? w.m / total : 0,
    v: present.v ? w.v / total : 0,
    s: present.s ? w.s / total : 0,
  }
}

type StockDetailTab = 'summary' | 'technicals' | 'setups' | 'ai' | 'peers'

function parseStockDetailTab(raw: string | null | undefined): StockDetailTab {
  const v = (raw || '').trim().toLowerCase()
  if (v === 'technicals' || v === 'setups' || v === 'ai' || v === 'peers') return v
  return 'summary'
}

type NavGroupDefinition = {
  label: string
  items: Array<{ label: string; id: string }>
}

const TICKER_NAV_GROUPS: Record<StockDetailTab, NavGroupDefinition> = {
  summary: {
    label: 'Summary',
    items: [
      { label: 'Grade', id: 'summary-grade' },
      { label: 'Factors', id: 'summary-factors' },
      { label: 'Fundamentals', id: 'summary-fundamentals' },
    ],
  },
  technicals: {
    label: 'Technicals',
    items: [
      { label: 'Price chart', id: 'technicals-price' },
      { label: 'Indicators', id: 'technicals-indicators' },
    ],
  },
  setups: {
    label: 'Setups',
    items: [
      { label: 'Hits', id: 'setups-hits' },
      { label: 'Explanation', id: 'setups-explanation' },
      { label: 'History', id: 'setups-history' },
    ],
  },
  ai: {
    label: 'AI Snapshot',
    items: [
      { label: 'Snapshot', id: 'ai-snapshot' },
      { label: 'Scenarios', id: 'ai-scenarios' },
      { label: 'Catalysts', id: 'ai-catalysts' },
      { label: 'Risks', id: 'ai-risks' },
    ],
  },
  peers: {
    label: 'Peers',
    items: [
      { label: 'Peer list', id: 'peers-list' },
      { label: 'Compare CTA', id: 'peers-compare' },
    ],
  },
}

function DetailSection({
  id,
  title,
  subtitle,
  icon,
  defaultOpen,
  children,
}: {
  id?: string
  title: string
  subtitle?: string
  icon?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <details
      id={id}
      open={defaultOpen}
      className="group relative overflow-hidden rounded-xl border border-outline/10 bg-card text-card-foreground shadow-sm transition hover:border-outline/16 dark:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.035)]"
    >
      <summary className="flex list-none items-start justify-between gap-3 px-4 py-3 sm:px-6 cursor-pointer">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-base font-semibold">
            {icon ? <span className="text-muted-foreground">{icon}</span> : null}
            <span className="truncate">{title}</span>
          </div>
          {subtitle ? <div className="text-xs text-muted-foreground">{subtitle}</div> : null}
        </div>
        <ChevronDownIcon className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="px-4 pb-4 sm:px-6 sm:pb-6 pt-0">{children}</div>
    </details>
  )
}

function Top3Grid({
  what,
  why,
  soWhat,
}: {
  what: ReactNode
  why: ReactNode
  soWhat: ReactNode
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Top3Card title="What" content={what} />
      <Top3Card title="Why" content={why} />
      <Top3Card title="So what" content={soWhat} />
    </div>
  )
}

function Top3Card({ title, content }: { title: string; content: ReactNode }) {
  return (
    <div className="rounded-xl border border-outline/10 bg-secondary/10 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="mt-1 text-sm text-foreground">{content}</div>
    </div>
  )
}

function derivePosture(grade?: string | null, netLabel?: string) {
  const g = (grade || '').trim().toUpperCase()
  if (g === 'A' || g === 'B') {
    return {
      label: 'Constructive',
      soWhat: `Strength-led posture${netLabel ? ` (${netLabel})` : ''}. Favor watchlist adds and disciplined entries.`,
    }
  }
  if (g === 'C') {
    return {
      label: 'Mixed',
      soWhat: `Balanced signals${netLabel ? ` (${netLabel})` : ''}. Wait for confirmation before sizing up.`,
    }
  }
  if (g === 'D' || g === 'F') {
    return {
      label: 'Defensive',
      soWhat: `Weak posture${netLabel ? ` (${netLabel})` : ''}. Prioritize risk control and patience.`,
    }
  }
  return {
    label: 'Unrated',
    soWhat: 'Insufficient data coverage. Recheck when scores populate.',
  }
}

function describeRsi(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return { label: 'RSI N/A', tone: 'Neutral' }
  if (value >= 70) return { label: `RSI ${value.toFixed(1)} (Overbought)`, tone: 'Overbought' }
  if (value <= 30) return { label: `RSI ${value.toFixed(1)} (Oversold)`, tone: 'Oversold' }
  return { label: `RSI ${value.toFixed(1)} (Neutral)`, tone: 'Neutral' }
}

function describeSmaTrend(sma20?: number | null, sma50?: number | null, sma200?: number | null) {
  if (sma20 == null || sma50 == null || sma200 == null) return 'Trend signal unavailable'
  if (sma20 > sma50 && sma50 > sma200) return 'Uptrend (SMA20 > SMA50 > SMA200)'
  if (sma20 < sma50 && sma50 < sma200) return 'Downtrend (SMA20 < SMA50 < SMA200)'
  return 'Mixed trend (SMAs not aligned)'
}

function describeMomentum(ret20?: number | null, ret60?: number | null) {
  const r20 = ret20 != null && Number.isFinite(ret20) ? ret20 : null
  const r60 = ret60 != null && Number.isFinite(ret60) ? ret60 : null
  if (r20 == null && r60 == null) return { label: 'Momentum signals unavailable', detail: null }
  if (r20 != null && r60 != null) {
    if (r20 >= 0 && r60 >= 0) {
      return { label: 'Positive momentum', detail: `20D ${formatSignedPercent(r20, 1)} · 60D ${formatSignedPercent(r60, 1)}` }
    }
    if (r20 < 0 && r60 < 0) {
      return { label: 'Negative momentum', detail: `20D ${formatSignedPercent(r20, 1)} · 60D ${formatSignedPercent(r60, 1)}` }
    }
    if (r20 >= 0 && r60 < 0) {
      return { label: 'Short-term rebound vs weak 3M trend', detail: `20D ${formatSignedPercent(r20, 1)} · 60D ${formatSignedPercent(r60, 1)}` }
    }
    return { label: 'Short-term pullback vs positive 3M trend', detail: `20D ${formatSignedPercent(r20, 1)} · 60D ${formatSignedPercent(r60, 1)}` }
  }
  if (r20 != null) {
    return { label: r20 >= 0 ? 'Short-term momentum' : 'Short-term weakness', detail: `20D ${formatSignedPercent(r20, 1)}` }
  }
  if (r60 != null) {
    return { label: r60 >= 0 ? 'Mid-term momentum' : 'Mid-term weakness', detail: `60D ${formatSignedPercent(r60, 1)}` }
  }
  return { label: 'Momentum signals unavailable', detail: null }
}

function describeVolatility(volZ20?: number | null) {
  if (volZ20 == null || !Number.isFinite(volZ20)) return 'Volatility signal unavailable'
  const z = Number(volZ20)
  if (z >= 1) return `Volatility elevated (Z ${z.toFixed(2)})`
  if (z <= -1) return `Volatility muted (Z ${z.toFixed(2)})`
  return `Volatility normal (Z ${z.toFixed(2)})`
}

function deriveTechnicalSoWhat({
  sma20,
  sma50,
  sma200,
  latestPrice,
  ret20,
  ret60,
  rsiTone,
  macdHist,
  volZ20,
}: {
  sma20?: number | null
  sma50?: number | null
  sma200?: number | null
  latestPrice?: number | null
  ret20?: number | null
  ret60?: number | null
  rsiTone: 'Overbought' | 'Oversold' | 'Neutral'
  macdHist?: number | null
  volZ20?: number | null
}) {
  const hasSmAs = sma20 != null && sma50 != null && sma200 != null
  const price = latestPrice != null && Number.isFinite(latestPrice) ? Number(latestPrice) : null
  const hasPrice = price != null
  const priceBelowAll = hasSmAs && hasPrice && price! < sma20! && price! < sma50! && price! < sma200!
  const priceAboveAll = hasSmAs && hasPrice && price! > sma20! && price! > sma50! && price! > sma200!
  const priceBelow200 = hasSmAs && hasPrice && price! < sma200!
  const trend =
    hasSmAs && sma20! > sma50! && sma50! > sma200!
      ? 'up'
      : hasSmAs && sma20! < sma50! && sma50! < sma200!
        ? 'down'
        : hasSmAs
          ? 'mixed'
          : 'unknown'

  const r20 = ret20 != null && Number.isFinite(ret20) ? ret20 : null
  const r60 = ret60 != null && Number.isFinite(ret60) ? ret60 : null
  const momentum =
    r20 != null && r60 != null
      ? r20 >= 0 && r60 >= 0
        ? 'up'
        : r20 < 0 && r60 < 0
          ? 'down'
          : r20 >= 0 && r60 < 0
            ? 'rebound'
            : 'pullback'
      : r20 != null
        ? r20 >= 0
          ? 'up'
          : 'down'
        : r60 != null
          ? r60 >= 0
            ? 'up'
            : 'down'
          : 'unknown'

  const macdSignal = macdHist == null || !Number.isFinite(macdHist) ? 'unknown' : macdHist >= 0 ? 'pos' : 'neg'

  let message = 'Mixed signals. Wait for cleaner trend confirmation.'
  if (trend === 'up') {
    if (priceBelowAll) {
      message = 'Price below SMA20/50/200; trend structure damaged. Wait for a base and reclaim.'
    } else if (priceBelow200) {
      message = 'Price below SMA200 despite uptrend signals. Wait for reclaim before adding risk.'
    } else
    if (momentum === 'up' && macdSignal === 'pos') {
      message = rsiTone === 'Overbought'
        ? 'Uptrend intact but stretched. Favor pullbacks over chasing.'
        : 'Uptrend aligned with momentum. Trend-following setups favored.'
    } else if (momentum === 'pullback') {
      message = 'Uptrend intact with a short-term pullback. Watch for support near fast averages.'
    } else if (momentum === 'rebound') {
      message = 'Potential reversal attempt. Wait for follow-through above key averages.'
    } else {
      message = 'Uptrend structure intact. Wait for momentum to re-accelerate.'
    }
  } else if (trend === 'down') {
    if (priceAboveAll) {
      message = 'Price reclaimed SMA20/50/200 inside a downtrend. Wait for confirmation before sizing up.'
    } else
    if (momentum === 'down' && macdSignal === 'neg') {
      message = rsiTone === 'Oversold'
        ? 'Downtrend stretched. Avoid new shorts; wait for base or stabilization.'
        : 'Downtrend intact. Avoid longs until momentum stabilizes.'
    } else if (momentum === 'rebound') {
      message = 'Bear trend with a short-term bounce. Treat rallies as resistance.'
    } else {
      message = 'Downtrend signals dominate. Patience and risk control favored.'
    }
  } else if (trend === 'mixed') {
    if (priceBelowAll) {
      message = 'Trend mixed but price below key averages. Patience until reclaim.'
    } else if (priceAboveAll) {
      message = 'Trend mixed with price above key averages. Wait for alignment before sizing up.'
    } else if (rsiTone === 'Overbought') {
      message = 'Range-like trend. Overbought signals favor mean-reversion discipline.'
    } else if (rsiTone === 'Oversold') {
      message = 'Range-like trend. Oversold signals favor patience and confirmation.'
    } else {
      message = 'Trend mixed. Wait for a breakout or clearer direction.'
    }
  } else {
    if (priceBelowAll) message = 'Price below key averages. Risk elevated; wait for stabilization.'
    else if (rsiTone === 'Overbought') message = 'Momentum stretched. Favor patience and defined risk.'
    else if (rsiTone === 'Oversold') message = 'Potential mean-reversion zone. Wait for stabilization.'
  }

  if (volZ20 != null && Number.isFinite(volZ20)) {
    if (volZ20 >= 1) {
      message += ' Volatility elevated; size smaller and use wider stops.'
    } else if (volZ20 <= -1) {
      message += ' Volatility muted; breakouts may need confirmation.'
    }
  }

  return message
}

function fmtScenarioValue(price?: number, prob?: number) {
  return `${formatUsd(price ?? null)} (p=${fmtProbability(prob)})`
}

function fmtProbability(prob?: number | null) {
  if (prob == null || Number.isNaN(Number(prob))) return '—'
  return `${Math.round(Number(prob))}%`
}

function extractAiDrivers(ai: any): string[] {
  const catalysts = [
    ...((ai?.catalysts?.shortTerm as any[]) ?? []),
    ...((ai?.catalysts?.longTerm as any[]) ?? []),
  ]
    .map((c) => (c?.title || c?.description || '').toString().trim())
    .filter(Boolean)
  if (catalysts.length) return catalysts.slice(0, 6)

  const seed = (ai?.analyst_summary?.bull_case || ai?.commentary || '').toString()
  return splitToSentences(seed).slice(0, 4)
}

function extractAiRisks(ai: any): string[] {
  const risks = [
    ...((ai?.risks?.macro as string[]) ?? []),
    ...((ai?.risks?.headline as string[]) ?? []),
    ...((ai?.risks?.data_gaps as string[]) ?? []),
  ]
    .map((r) => (r || '').toString().trim())
    .filter(Boolean)
  return risks.slice(0, 6)
}

function buildAiSources(ai: any): string[] {
  const sources: string[] = []
  if (ai?.source_name) {
    sources.push(`Model source: ${ai.source_name}`)
  } else {
    sources.push('Model source: internal (not provided)')
  }
  const aiAsOf = ai?.analysis_date ?? ai?.as_of_date
  if (aiAsOf) {
    sources.push(`Analysis date: ${formatEasternDate(aiAsOf)}`)
  }
  return sources
}

function formatPeerFallbackSummary(peer: SimilarPeerItem, fallback: SimilarPeersResponse | null): string {
  const sector = fallback?.sector?.trim()
  const targetCap = typeof fallback?.market_cap === 'number' && Number.isFinite(fallback.market_cap)
    ? fallback.market_cap
    : null
  const peerCap = typeof peer.market_cap === 'number' && Number.isFinite(peer.market_cap)
    ? peer.market_cap
    : null
  const parts: string[] = []
  if (sector) parts.push(`Same sector: ${sector}`)
  if (peerCap != null) {
    parts.push(`Cap ${formatUsdCompactFromMillions(peerCap / 1_000_000)}`)
  } else if (targetCap != null) {
    parts.push('Similar market cap')
  }
  return parts.length ? parts.join(' · ') : 'Similar market cap'
}

function resolveAiAsOf(ai: any): string | null {
  const raw = ai?.analysis_date ?? ai?.as_of_date
  if (!raw) return null
  return String(raw)
}

function splitToSentences(text: string): string[] {
  const cleaned = text.replace(/\s+/g, ' ').trim()
  if (!cleaned) return []
  return cleaned.split(/(?<=[.!?])\s+/).map((p) => p.trim()).filter(Boolean)
}

export async function StockDetailView({
  symbol,
  variant,
  tab,
  includeSetups = false,
}: {
  symbol: string
  variant?: 'page' | 'modal' | 'panel'
  tab?: string
  includeSetups?: boolean
}) {
  const viewVariant = variant ?? 'panel'
  const rawTab = (tab || '').trim()
  const requestedTab: StockDetailTab = parseStockDetailTab(rawTab)
  const isTabbed = viewVariant !== 'page' || rawTab.length > 0
  const normalizedSymbol = (symbol || '').trim().toUpperCase()
  if (!normalizedSymbol) notFound()
  const canonicalPath = `/ticker/${encodeURIComponent(normalizedSymbol)}`
  const activeTab: StockDetailTab = isTabbed ? requestedTab : 'summary'
  const detailTabs: Array<{ key: StockDetailTab; label: string }> = [
    { key: 'summary', label: 'Summary' },
    { key: 'technicals', label: 'Technicals' },
    { key: 'setups', label: UI_TERMS.setupHits },
    { key: 'ai', label: 'AI Snapshot' },
    { key: 'peers', label: 'Peers' },
  ]
  const tabHref = (next: StockDetailTab) => {
    const params = new URLSearchParams()
    params.set('tab', next)
    return `${canonicalPath}?${params.toString()}`
  }
  const loadSetupsHref = (() => {
    const params = new URLSearchParams()
    params.set('tab', 'summary')
    params.set('include_setups', 'true')
    return `${canonicalPath}?${params.toString()}`
  })()
  const tabLinks = detailTabs.map((tabItem) => ({
    label: tabItem.label,
    href: tabItem.key === 'technicals' ? `${tabHref(tabItem.key)}#technicals-price` : tabHref(tabItem.key),
    active: activeTab === tabItem.key,
  }))

  const base = getInternalApiBase()
  const encoded = encodeURIComponent(normalizedSymbol)

  const technicalsSeriesDays = 400
  const sparkIndicators = ['RSI14', 'MACD_HIST', 'ATR14']
  const seriesParams = new URLSearchParams({
    symbol: normalizedSymbol,
    indicators: sparkIndicators.join(','),
    days: String(technicalsSeriesDays),
  })
  const setupWindowDays = 3
  const setupSymbolParams = new URLSearchParams({
    symbol: normalizedSymbol,
    window_days: String(setupWindowDays),
  })

  const wantsSummary = !isTabbed || activeTab === 'summary'
  const wantsTechnicals = !isTabbed || activeTab === 'technicals'
  const wantsSetups = !isTabbed || activeTab === 'setups' || includeSetups
  const wantsPeers = !isTabbed || activeTab === 'peers'
  const wantsFundamentals = SHOW_RAW_DATA && (!isTabbed || activeTab === 'summary')
  const shouldPrefetch = isTabbed

  const assetDetailPromise = fetchJson<AssetDetail>(`${base}/api/v1/grading/asset/${encoded}`, {
    next: { revalidate: 300, tags: ['asset', `asset:${normalizedSymbol}`] },
  })
  const technicalsLatestPromise = wantsTechnicals
    ? fetchJson<TechnicalsSnapshot>(`${base}/api/v1/technicals/latest?symbol=${encoded}`, {
        next: { revalidate: 300, tags: ['technicals', `technicals:${normalizedSymbol}`] },
      })
    : Promise.resolve(null)
  const latestPricePromise = wantsTechnicals
    ? fetchJson<LatestAdjList>(
        `${base}/api/v1/prices/latest?symbol=${encoded}&limit=1&sort_by=date&sort_order=desc`,
        { next: { revalidate: 60, tags: ['prices', `prices:${normalizedSymbol}`] } },
      )
    : Promise.resolve(null)
  const technicalsSeriesPromise = wantsTechnicals
    ? fetchJson<TechnicalsSeriesResponse>(`${base}/api/v1/technicals/series?${seriesParams.toString()}`, {
        next: { revalidate: 300, tags: ['technicals', `technicals-series:${normalizedSymbol}`] },
      })
    : Promise.resolve(null)
  const setupSymbolPromise = wantsSetups
    ? fetchJson<SetupSymbolResponse>(`${base}/api/v1/screener/setups/symbol?${setupSymbolParams.toString()}`, {
        next: { revalidate: 300, tags: ['screener', 'setups', `setups:${normalizedSymbol}`] },
      })
    : Promise.resolve(null)
  const modelWeightsPromise = fetchJson<ModelWeights>(`${base}/api/v1/grading/weights`, {
    next: { revalidate: 900, tags: ['grading', 'weights'] },
  })
  const fundamentalsMetricCodes = [
    'mktcap',
    'beta',
    'sharesoutstanding',
    'peexclxor',
    'peinclxor',
    'pebexclxor',
    'epsactual',
    'aepsxclxor',
    'aepsinclxo',
    'aepsnorm',
    'abepsxclxo',
    'ttmpr2rev',
    'ttmprfcfps',
    'aprfcfps',
    'ttmfcf',
    'ttmfcfshr',
    'revchngyr',
    'epschngyr',
    'ttmgrosmgn',
    'ttmopmgn',
    'netdebt_a',
    'qcurratio',
  ]
  const fundamentalsPromise: Promise<FundamentalsSnapshot | null> = wantsFundamentals
    ? (() => {
        const fundamentalParams = new URLSearchParams({
          symbol: normalizedSymbol,
          metrics: fundamentalsMetricCodes.join(','),
        })
        return fetchJson<FundamentalsSnapshot>(`${base}/api/v1/fundamentals/latest?${fundamentalParams.toString()}`, {
          next: { revalidate: 300, tags: ['fundamentals', `fundamentals:${normalizedSymbol}`] },
        })
      })()
    : Promise.resolve(null)

  if (shouldPrefetch && !wantsTechnicals) {
    prefetchJson(`${base}/api/v1/technicals/latest?symbol=${encoded}`, {
      next: { revalidate: 300, tags: ['technicals', `technicals:${normalizedSymbol}`] },
    })
    prefetchJson(`${base}/api/v1/technicals/series?${seriesParams.toString()}`, {
      next: { revalidate: 300, tags: ['technicals', `technicals-series:${normalizedSymbol}`] },
    })
  }
  if (shouldPrefetch && !wantsSetups && activeTab !== 'summary') {
    prefetchJson(`${base}/api/v1/screener/setups/symbol?${setupSymbolParams.toString()}`, {
      next: { revalidate: 300, tags: ['screener', 'setups', `setups:${normalizedSymbol}`] },
    })
  }
  if (shouldPrefetch && SHOW_RAW_DATA && !wantsFundamentals) {
    const fundamentalParams = new URLSearchParams({
      symbol: normalizedSymbol,
      metrics: fundamentalsMetricCodes.join(','),
    })
    prefetchJson(`${base}/api/v1/fundamentals/latest?${fundamentalParams.toString()}`, {
      next: { revalidate: 300, tags: ['fundamentals', `fundamentals:${normalizedSymbol}`] },
    })
  }

  const [
    assetDetail,
    technicalsLatest,
    technicalsSeries,
    latestPriceList,
    setupSymbolView,
    modelWeights,
    fundamentalsLatest,
  ] = await Promise.all([
    assetDetailPromise,
    technicalsLatestPromise,
    technicalsSeriesPromise,
    latestPricePromise,
    setupSymbolPromise,
    modelWeightsPromise,
    fundamentalsPromise,
  ])
  if (!assetDetail) notFound()

  let fundamentalsByCode: Record<string, number | null | undefined> = {}
  let marketCapMm: number | null = null
  let sharesOutstanding: number | null = null
  let priceFromMarketCap: number | null = null
  let peTtmValue: number | null = null
  let peIsDerived = false
  let pfcfValue: number | null = null
  let pfcfIsDerived = false

  if (SHOW_RAW_DATA) {
    fundamentalsByCode = (fundamentalsLatest?.metrics ?? []).reduce<Record<string, number | null | undefined>>((acc, m) => {
      acc[(m.metric_code || '').toLowerCase()] = m.value ?? null
      return acc
    }, {})
    marketCapMm = fundamentalsByCode['mktcap'] ?? null
    sharesOutstanding = fundamentalsByCode['sharesoutstanding'] ?? null
    priceFromMarketCap =
      typeof marketCapMm === 'number' && typeof sharesOutstanding === 'number' && sharesOutstanding !== 0
        ? (marketCapMm * 1_000_000) / sharesOutstanding
        : null
    const epsFallback =
      fundamentalsByCode['epsactual'] ??
      fundamentalsByCode['aepsxclxor'] ??
      fundamentalsByCode['aepsinclxo'] ??
      fundamentalsByCode['aepsnorm'] ??
      fundamentalsByCode['abepsxclxo'] ??
      null
    peTtmValue =
      fundamentalsByCode['peexclxor'] ??
      fundamentalsByCode['peinclxor'] ??
      fundamentalsByCode['pebexclxor'] ??
      (priceFromMarketCap !== null && epsFallback !== null && epsFallback !== 0
        ? priceFromMarketCap / epsFallback
        : null) ??
      null
    peIsDerived = peTtmValue !== null && (fundamentalsByCode['peexclxor'] ?? fundamentalsByCode['peinclxor'] ?? fundamentalsByCode['pebexclxor']) == null
    pfcfValue =
      fundamentalsByCode['ttmprfcfps'] ??
      fundamentalsByCode['aprfcfps'] ??
      (priceFromMarketCap !== null && fundamentalsByCode['ttmfcfshr'] !== null && fundamentalsByCode['ttmfcfshr'] !== 0
        ? priceFromMarketCap / (fundamentalsByCode['ttmfcfshr'] as number)
        : null) ??
      (marketCapMm !== null && fundamentalsByCode['ttmfcf'] !== null && fundamentalsByCode['ttmfcf'] !== 0
        ? (marketCapMm as number) / (fundamentalsByCode['ttmfcf'] as number)
        : null) ??
      null
    pfcfIsDerived = pfcfValue !== null && (fundamentalsByCode['ttmprfcfps'] ?? fundamentalsByCode['aprfcfps']) == null
  }

  const setupDays = setupSymbolView?.days ?? []
  const latestSetupDay = setupDays.reduce<SetupHitsDay | null>((best, day) => {
    if (!day?.as_of_date) return best
    if (!best?.as_of_date) return day
    return day.as_of_date > best.as_of_date ? day : best
  }, null)

  const setupSummary = setupSymbolView?.summary as any
  const netBias = (setupSummary?.net_bias || '').toString()
  const netStrength = (setupSummary?.net_strength || '').toString()
  const netLabel = netBias === 'bearish' ? 'Net Bearish' : netBias === 'bullish' ? 'Net Bullish' : 'Net Neutral'

  const aiAnalysisHref = `/ai-analysis/${encodeURIComponent(normalizedSymbol)}`
  const windowSetupHits = setupDays.flatMap((day) => (Array.isArray(day?.hits) ? day.hits : []))
  const hasSetupData = Boolean(setupSymbolView)
  const setupHitCountLabel = hasSetupData ? String(windowSetupHits.length) : '—'
  const netLabelDisplay = hasSetupData ? netLabel : 'Net —'
  const screenBuckets = (() => {
    const bullish = new Map<string, number>()
    const bearish = new Map<string, number>()
    windowSetupHits.forEach((hit) => {
      const src = (hit?.source || '').trim()
      if (!src) return
      const w = typeof hit.weight === 'number' && Number.isFinite(hit.weight) ? hit.weight : 0
      const target = hit.bias === 'bearish' ? bearish : bullish
      target.set(src, Math.max(target.get(src) ?? 0, w))
    })

    const toSorted = (m: Map<string, number>) =>
      Array.from(m.entries())
        .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]))
        .map(([source]) => source)

    return {
      bullish: toSorted(bullish),
      bearish: toSorted(bearish),
    }
  })()

  const scores = {
    momentum: assetDetail.current_grade?.momentum_score ?? null,
    value: assetDetail.current_grade?.value_score ?? null,
    sentiment: assetDetail.current_grade?.sentiment_score ?? null,
  }

  const ew = effectiveWeights(modelWeights, scores)
  const contributions = [
    { key: 'Momentum', weight: ew.m, score: scores.momentum, barClass: 'bg-status-info/60', textClass: 'text-status-info' },
    { key: 'Value', weight: ew.v, score: scores.value, barClass: 'bg-status-success/55', textClass: 'text-status-success' },
    { key: 'Sentiment', weight: ew.s, score: scores.sentiment, barClass: 'bg-status-model/55', textClass: 'text-status-model' },
  ]
    .filter((r) => r.weight > 0 && typeof r.score === 'number' && Number.isFinite(r.score))
    .map((r) => ({ ...r, contrib: r.weight * Number(r.score) }))
  const contribTotal = contributions.reduce((acc, r) => acc + r.contrib, 0) || 1
  const leadingContribution = contributions.reduce<typeof contributions[number] | null>((best, r) => {
    if (!best) return r
    return r.contrib > best.contrib ? r : best
  }, null)

  const deltas = {
    m7: scoreSeriesDelta(assetDetail.score_history ?? [], 'momentum', 7),
    m21: scoreSeriesDelta(assetDetail.score_history ?? [], 'momentum', 21),
    v7: scoreSeriesDelta(assetDetail.score_history ?? [], 'value', 7),
    v21: scoreSeriesDelta(assetDetail.score_history ?? [], 'value', 21),
    s7: scoreSeriesDelta(assetDetail.score_history ?? [], 'sentiment', 7),
    s21: scoreSeriesDelta(assetDetail.score_history ?? [], 'sentiment', 21),
  }

  const bullishTop = screenBuckets.bullish.slice(0, 3).join(', ')
  const bearishTop = screenBuckets.bearish.slice(0, 3).join(', ')

  const rsiSpark =
    technicalsSeries?.series?.RSI14?.filter((p) => p && typeof p.value === 'number' && Number.isFinite(p.value)).map((p) => ({ x: p.date, y: Number(p.value) })) ??
    []
  const atrSpark =
    technicalsSeries?.series?.ATR14?.filter((p) => p && typeof p.value === 'number' && Number.isFinite(p.value)).map((p) => ({ x: p.date, y: Number(p.value) })) ??
    []
  const macdHistSpark =
    technicalsSeries?.series?.MACD_HIST?.filter((p) => p && typeof p.value === 'number' && Number.isFinite(p.value)).map((p) => ({ x: p.date, y: Number(p.value) })) ??
    []
  const macdHistMaxAbs = (() => {
    const ys = macdHistSpark.map((p) => p.y).filter((y) => Number.isFinite(y))
    if (!ys.length) return 1
    const m = Math.max(...ys.map((y) => Math.abs(y)))
    return m > 0 ? m : 1
  })()

  const rsiDescriptor = describeRsi(technicalsLatest?.rsi14)
  const smaTrendDescriptor = describeSmaTrend(technicalsLatest?.sma20, technicalsLatest?.sma50, technicalsLatest?.sma200)
  const macdHistValue = technicalsLatest?.macd_hist
  const latestPrice = (() => {
    const item = latestPriceList?.items?.[0]
    const candidate = item?.adj_close_px ?? item?.close_px ?? null
    return typeof candidate === 'number' && Number.isFinite(candidate) ? candidate : null
  })()
  const macdDescriptor =
    macdHistValue == null || !Number.isFinite(macdHistValue)
      ? 'MACD hist N/A'
      : macdHistValue > 0
        ? `MACD hist +${macdHistValue.toFixed(2)}`
        : `MACD hist ${macdHistValue.toFixed(2)}`
  const momentumDescriptor = describeMomentum(technicalsLatest?.ret_20d, technicalsLatest?.ret_60d)
  const volatilityDescriptor = describeVolatility(technicalsLatest?.vol_z20)
  const technicalSoWhat = deriveTechnicalSoWhat({
    sma20: technicalsLatest?.sma20,
    sma50: technicalsLatest?.sma50,
    sma200: technicalsLatest?.sma200,
    latestPrice,
    ret20: technicalsLatest?.ret_20d,
    ret60: technicalsLatest?.ret_60d,
    rsiTone: rsiDescriptor.tone as 'Overbought' | 'Oversold' | 'Neutral',
    macdHist: macdHistValue,
    volZ20: technicalsLatest?.vol_z20,
  })
  const technicalReadout = [
    { label: 'Trend', value: smaTrendDescriptor },
    {
      label: 'Momentum',
      value: momentumDescriptor.detail ? `${momentumDescriptor.label} · ${momentumDescriptor.detail}` : momentumDescriptor.label,
    },
    { label: 'RSI / MACD', value: `${rsiDescriptor.label} · ${macdDescriptor}` },
    { label: 'Volatility', value: volatilityDescriptor },
  ]

  const aiDrivers = extractAiDrivers(assetDetail.ai_analysis)
  const aiRisks = extractAiRisks(assetDetail.ai_analysis)
  const aiSources = buildAiSources(assetDetail.ai_analysis)

  const aiPeers = Array.isArray(assetDetail.ai_analysis?.peers)
    ? assetDetail.ai_analysis.peers
    : []
  const wantsPeerFallback = wantsPeers && aiPeers.length === 0
  const fallbackPeers = wantsPeerFallback
    ? await fetchJson<SimilarPeersResponse>(`${base}/api/v1/grading/peers/similar?symbol=${encoded}&limit=3`, {
        next: { revalidate: 900, tags: ['grades', 'peers', `peers:${normalizedSymbol}`] },
      })
    : null
  const peersList = aiPeers.length
    ? aiPeers
    : (fallbackPeers?.items ?? []).map((peer) => ({
        peer_symbol: peer.symbol,
        summary: formatPeerFallbackSummary(peer, fallbackPeers),
      }))

  const normalizePeerSymbol = (raw: string) => {
    const trimmed = (raw || '').trim()
    const upper = trimmed.toUpperCase()
    if (!upper) return { display: '', lookup: [] as string[] }

    let display = upper
    if (display.includes(':')) {
      display = display.split(':').pop() || display
    }
    if (display.includes(' ')) {
      display = display.split(' ')[0] || display
    }

    const lookup = new Set<string>()
    lookup.add(display)

    const dotParts = display.split('.')
    if (dotParts.length === 2) {
      const suffix = dotParts[1]
      const isExchangeSuffix = suffix.length >= 2 && suffix.length <= 3 && /^[A-Z]+$/.test(suffix)
      if (isExchangeSuffix) {
        lookup.add(dotParts[0])
      }
    }

    return { display, lookup: Array.from(lookup) }
  }

  const normalizedPeers: { peer: any; normalized: { display: string; lookup: string[] } }[] =
    peersList.map((peer: any) => ({
      peer,
      normalized: normalizePeerSymbol(peer?.peer_symbol || ''),
    }))

  const peerSymbols = Array.from(
    new Set(
      normalizedPeers
        .flatMap(({ normalized }) => normalized.lookup)
        .filter(Boolean)
    )
  ).slice(0, 25)

  if (shouldPrefetch && !wantsPeers && peerSymbols.length) {
    const peerParams = new URLSearchParams()
    peerSymbols.forEach((sym) => peerParams.append('symbols', sym))
    prefetchJson(`${base}/api/v1/grading/grades/batch?${peerParams.toString()}`, {
      next: { revalidate: 600, tags: ['grades', 'grade', 'asset', 'peer-grades'] },
    })
  }

  let peerGrades: PeerGradesResponse | null = null
  if (wantsPeers && peerSymbols.length) {
    const peerParams = new URLSearchParams()
    peerSymbols.forEach((sym) => peerParams.append('symbols', sym))
    peerGrades = await fetchJson<PeerGradesResponse>(
      `${base}/api/v1/grading/grades/batch?${peerParams.toString()}`,
      { next: { revalidate: 600, tags: ['grades', 'grade', 'asset', 'peer-grades'] } }
    )
  }

  const peerGradeItems = peerGrades && Array.isArray(peerGrades.items) ? peerGrades.items : []
  const peerGradeMap = Object.fromEntries(
    peerGradeItems
      .map((it) => ({
        symbol: (it.symbol || '').trim().toUpperCase(),
        grade: it.overall_grade,
      }))
      .filter((it) => it.symbol)
      .map((it) => [it.symbol, it.grade])
  )

  const peerGradeCounts = peerGradeItems.reduce<Record<string, number>>((acc, item) => {
    const g = (item?.overall_grade || 'N/A').toUpperCase()
    acc[g] = (acc[g] ?? 0) + 1
    return acc
  }, {})
  const peerGradeSpread = ['A', 'B', 'C', 'D', 'F']
    .map((g) => (peerGradeCounts[g] ? `${g} ${peerGradeCounts[g]}` : null))
    .filter(Boolean)
    .join(' · ')
  const topPeerPreview = normalizedPeers
    .slice(0, 3)
    .map(({ normalized }) => {
      const grade = normalized.lookup.map((candidate) => peerGradeMap[candidate]).find((candidate) => candidate)
      return grade ? `${normalized.display} (${grade})` : normalized.display
    })
    .filter(Boolean)
    .join(', ')

  const siteUrl = getCanonicalSiteUrl()
  const canonicalUrl = `${siteUrl}/ticker/${encodeURIComponent(normalizedSymbol)}`
  const ldJson = (() => {
    if (viewVariant !== 'page') return null
    const company = (assetDetail.company_name || '').trim()
    const grade = (assetDetail.current_grade?.overall_grade || '').trim()
    const asOf = (assetDetail.current_grade?.date || '').trim()
    const title = `${normalizedSymbol}${company ? ` - ${company}` : ''}${grade ? ` - Grade ${grade}` : ''}`
    const description = `${company ? `${company} (${normalizedSymbol})` : normalizedSymbol} stock grade${grade ? ` (${grade})` : ''} with technical indicators and fundamentals.${asOf ? ` As of ${asOf}.` : ''}`

    const payload = {
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      name: title,
      url: canonicalUrl,
      dateModified: asOf || undefined,
      description,
      isPartOf: {
        '@type': 'WebSite',
        name: 'RankAlpha',
        url: siteUrl,
      },
      about: {
        '@type': 'Corporation',
        name: company || normalizedSymbol,
        tickerSymbol: normalizedSymbol,
      },
    }

    return JSON.stringify(payload).replace(/</g, '\\u003c')
  })()

  const posture = derivePosture(assetDetail.current_grade?.overall_grade, hasSetupData ? netLabel : undefined)
  const compareHref = `/compare?t=${encodeURIComponent(normalizedSymbol)}`
  const chartHref = `${tabHref('technicals')}#technicals-price`
  const anchorClass = 'scroll-mt-28'
  const crossRef = (() => {
    if (!leadingContribution?.key) return null
    if (leadingContribution.key === 'Value') {
      return { label: 'See fundamentals', href: '#summary-fundamentals' }
    }
    if (leadingContribution.key === 'Momentum') {
      const href = isTabbed ? `${tabHref('technicals')}#technicals-price` : '#technicals-price'
      return { label: 'See technicals', href }
    }
    if (leadingContribution.key === 'Sentiment') {
      const href = isTabbed ? `${tabHref('ai')}#ai-snapshot` : '#ai-snapshot'
      return { label: 'See AI snapshot', href }
    }
    return null
  })()

  const navGroups = (isTabbed
    ? [TICKER_NAV_GROUPS[activeTab]]
    : [
        TICKER_NAV_GROUPS.summary,
        TICKER_NAV_GROUPS.technicals,
        TICKER_NAV_GROUPS.setups,
        TICKER_NAV_GROUPS.ai,
        TICKER_NAV_GROUPS.peers,
      ]
  ).map((group) => ({
    label: group.label,
    items: group.items.map((item) => ({ label: item.label, href: `#${item.id}` })),
  }))

  const baseTargetPrice = assetDetail.ai_analysis?.scenarios?.base?.price ?? null
  const todayEastern = formatEasternDate(new Date())
  const nextEarningsDateCandidate = assetDetail.next_earnings_date
    ? formatEasternDate(assetDetail.next_earnings_date)
    : null
  const nextEarningsDate =
    nextEarningsDateCandidate && nextEarningsDateCandidate >= todayEastern
      ? nextEarningsDateCandidate
      : null
  const nextEarningsTime = formatEarningsTime(assetDetail.next_earnings_time)
  const nextEarningsLabel = nextEarningsDate
    ? `${nextEarningsDate}${nextEarningsTime ? ` · ${nextEarningsTime}` : ''}`
    : null

  const summaryStrip = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-foreground">M</span>
        <span className="text-status-info">{formatScore(scores.momentum)}</span>
        <span className="font-semibold text-foreground">V</span>
        <span className="text-status-success">{formatScore(scores.value)}</span>
        <span className="font-semibold text-foreground">S</span>
        <span className="text-status-model">{formatScore(scores.sentiment)}</span>
      </div>
      <span className="h-3 w-px bg-outline/20" aria-hidden />
      <div className="flex items-center gap-1">
        <span className="font-semibold text-foreground">{formatSetupHitsLabel(setupWindowDays)}</span>
        <span>{setupHitCountLabel}</span>
        <span className="text-[11px]">· {netLabelDisplay}</span>
      </div>
      <span className="h-3 w-px bg-outline/20" aria-hidden />
      <div className="flex items-center gap-1">
        <span className="font-semibold text-foreground">{UI_TERMS.aiTargets}</span>
        <span>Base {formatUsd(assetDetail.ai_analysis?.scenarios?.base?.price ?? null)}</span>
        <span>• Bull {formatUsd(assetDetail.ai_analysis?.scenarios?.bull?.price ?? null)}</span>
        <span>• Bear {formatUsd(assetDetail.ai_analysis?.scenarios?.bear?.price ?? null)}</span>
        <AiTargetSpread symbol={normalizedSymbol} baseTargetPrice={baseTargetPrice} />
      </div>
      {nextEarningsLabel ? (
        <>
          <span className="h-3 w-px bg-outline/20" aria-hidden />
          <div className="flex items-center gap-1">
            <span className="font-semibold text-foreground">Next earnings</span>
            <span>{nextEarningsLabel}</span>
          </div>
        </>
      ) : null}
    </div>
  )

  const fundamentalsVendor = fundamentalsLatest?.latest_source_name
  const fundamentalsVendorLabel = fundamentalsVendor
    ? `Vendor: ${fundamentalsVendor}${fundamentalsLatest?.latest_source_version ? ` v${fundamentalsLatest.latest_source_version}` : ''}`
    : null
  const scoresModelLabel = modelWeights?.method ? `Model: ${modelWeights.method}` : 'Model: default'
  const aiModelLabel = assetDetail.ai_analysis?.source_name
    ? `Model: ${assetDetail.ai_analysis.source_name}`
    : 'Model: internal'
  const priceFallbackAsOf = technicalsLatest?.as_of_date ?? assetDetail.current_grade?.date ?? null
  const aiAsOf = resolveAiAsOf(assetDetail.ai_analysis)
  const fundamentalsMissingReason =
    !SHOW_RAW_DATA
      ? 'Redacted'
      : fundamentalsLatest?.redacted
      ? (fundamentalsLatest.redaction_reason || 'Redacted')
      : 'No fundamentals yet'

  const showFundamentalsFreshness = wantsSummary
  const fundamentalsStatus: DataFreshnessItem['status'] =
    fundamentalsLatest?.latest_as_of_date ? 'ok' : 'missing'
  const scoresStatus: DataFreshnessItem['status'] =
    assetDetail.current_grade?.date ? 'ok' : 'missing'
  const hasAiMemo = Boolean(assetDetail.ai_analysis)
  const aiStatus: DataFreshnessItem['status'] = aiAsOf ? 'ok' : hasAiMemo ? 'mixed' : 'missing'
  const freshnessItems: DataFreshnessItem[] = []
  if (showFundamentalsFreshness) {
    freshnessItems.push({
      label: 'Fundamentals',
      asOf: fundamentalsLatest?.latest_as_of_date ?? null,
      source: fundamentalsVendorLabel,
      status: fundamentalsStatus,
      missingReason: fundamentalsLatest?.latest_as_of_date ? null : fundamentalsMissingReason,
    })
  }
  freshnessItems.push(
    {
      label: 'Scores',
      asOf: assetDetail.current_grade?.date ?? null,
      version: scoresModelLabel,
      status: scoresStatus,
      missingReason: assetDetail.current_grade?.date ? null : 'No scores yet',
    },
    {
      label: 'AI Memo',
      asOf: aiAsOf,
      version: aiModelLabel,
      status: aiStatus,
      missingReason: hasAiMemo ? null : 'No memo yet',
    },
  )

  const detailContent = (
    <div className="space-y-3">
      <RecentTickerTracker symbol={normalizedSymbol} companyName={assetDetail.company_name} />
      {ldJson ? (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: ldJson }} />
      ) : null}
      <TickerHeader
        symbol={normalizedSymbol}
        companyName={assetDetail.company_name}
        exchange={assetDetail.exchange}
        sector={assetDetail.sector}
        grade={assetDetail.current_grade?.overall_grade}
        gradeClassName={assetDetail.current_grade?.overall_grade ? getGradeBadgeColor(assetDetail.current_grade.overall_grade) : undefined}
        priceAsOf={priceFallbackAsOf}
        tabs={detailTabs}
        activeTab={activeTab}
        canonicalPath={canonicalPath}
        showTabs={isTabbed}
        summaryStrip={summaryStrip}
        chartHref={chartHref}
        variant={viewVariant}
      />
      <TickerFreshnessBar
        symbol={normalizedSymbol}
        items={freshnessItems}
        enablePriceHistory={false}
        priceFallbackAsOf={priceFallbackAsOf}
      />

      <div className="space-y-3">
        {!isTabbed || activeTab === 'summary' ? (
        <DetailSection
          id="summary"
          title="Summary"
          icon={<TrendingUpIcon className="h-4 w-4" aria-hidden />}
          defaultOpen
          subtitle={assetDetail.current_grade?.date ? `As of ${formatEasternDate(assetDetail.current_grade.date)}` : undefined}
        >
          <div id="summary-grade" className={anchorClass}>
            <Top3Grid
            what={
              <div className="space-y-1 text-sm">
                <div className="font-semibold text-foreground">
                  Grade {assetDetail.current_grade?.overall_grade || 'N/A'} · {posture.label}
                </div>
                <div className="text-xs text-muted-foreground">
                  Confidence {assetDetail.current_grade?.confidence || '-'} · {netLabelDisplay}
                </div>
                {SHOW_RAW_DATA && assetDetail.target_price != null ? (
                  <div className="text-xs text-muted-foreground">
                    Target {formatUsd(assetDetail.target_price)}
                  </div>
                ) : null}
              </div>
            }
            why={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>Momentum {formatScore(scores.momentum)} (Δ7d {formatSignedDelta(deltas.m7)})</div>
                <div>Value {formatScore(scores.value)} (Δ7d {formatSignedDelta(deltas.v7)})</div>
                <div>Sentiment {formatScore(scores.sentiment)} (Δ7d {formatSignedDelta(deltas.s7)})</div>
              </div>
            }
            soWhat={<span className="text-sm text-foreground">{posture.soWhat}</span>}
          />
          </div>
          {activeTab === 'summary' && !includeSetups ? (
            <div className="mt-3 rounded-xl border border-outline/10 bg-secondary/10 p-3 text-xs text-muted-foreground">
              <div className="font-semibold text-foreground">Setup hits not loaded</div>
              <p className="mt-1">Load setup hits to see net bias and recent triggers.</p>
              <Link
                href={loadSetupsHref}
                className="mt-2 inline-flex items-center justify-center rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary transition hover:bg-primary/20"
              >
                Load setup hits
              </Link>
            </div>
          ) : null}
          {leadingContribution ? (
            <div className="mt-3 text-xs text-muted-foreground">
              Lead driver: <span className="font-semibold text-foreground">{leadingContribution.key}</span>
              {crossRef ? (
                <>
                  {' '}·{' '}
                  {crossRef.href.startsWith('#') ? (
                    <a href={crossRef.href} className="font-semibold text-primary hover:underline">
                      {crossRef.label}
                    </a>
                  ) : (
                    <Link href={crossRef.href} className="font-semibold text-primary hover:underline">
                      {crossRef.label}
                    </Link>
                  )}
                </>
              ) : null}
            </div>
          ) : null}

          <div id="summary-factors" className={`${anchorClass} grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-4`}>
            <div className="text-center">
              <div className="text-lg font-semibold text-status-info sm:text-xl">{formatScore(assetDetail.current_grade.momentum_score)}</div>
              <div className="inline-flex items-center justify-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
                <span>Momentum</span>
                <TooltipCopyButton
                  tooltipKey="rankings.momentumScore"
                  iconSize="h-3.5 w-3.5"
                  buttonClassName="text-muted-foreground hover:text-foreground"
                />
              </div>
            </div>
            <div className="text-center">
              <div className="text-lg font-semibold text-status-success sm:text-xl">{formatScore(assetDetail.current_grade.value_score)}</div>
              <div className="inline-flex items-center justify-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
                <span>Value</span>
                <TooltipCopyButton
                  tooltipKey="rankings.valueScore"
                  iconSize="h-3.5 w-3.5"
                  buttonClassName="text-muted-foreground hover:text-foreground"
                />
              </div>
            </div>
            <div className="text-center">
              <div className="text-lg font-semibold text-status-model sm:text-xl">{formatScore(assetDetail.current_grade.sentiment_score)}</div>
              <div className="inline-flex items-center justify-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
                <span>Sentiment</span>
                <TooltipCopyButton
                  tooltipKey="rankings.sentimentScore"
                  iconSize="h-3.5 w-3.5"
                  buttonClassName="text-muted-foreground hover:text-foreground"
                />
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {contributions.map((r) => {
              const pct = Math.max(0, Math.min(1, r.contrib / contribTotal))
              const delta7 = r.key === 'Momentum' ? deltas.m7 : r.key === 'Value' ? deltas.v7 : deltas.s7
              const delta21 = r.key === 'Momentum' ? deltas.m21 : r.key === 'Value' ? deltas.v21 : deltas.s21
              return (
                <div key={r.key} className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{r.key}</div>
                    <div className="text-[11px] font-semibold text-muted-foreground">{Math.round(r.weight * 100)}%</div>
                  </div>
                  <div className="mt-1 flex items-baseline justify-between gap-2">
                    <div className={`text-lg font-semibold ${r.textClass}`}>{formatScore(r.score)}</div>
                    <div className="text-[11px] text-muted-foreground">
                      Δ7d {formatSignedDelta(delta7)} · Δ21d {formatSignedDelta(delta21)}
                    </div>
                  </div>
                  <div className="mt-2 h-1.5 w-full rounded-full bg-secondary/30">
                    <div className={`h-1.5 rounded-full ${r.barClass}`} style={{ width: `${Math.max(8, Math.round(pct * 100))}%` }} />
                  </div>
                </div>
              )
            })}
          </div>

          {assetDetail.current_grade?.grade_explanation ? (
            <div className="mt-4 rounded-xl border border-outline/10 bg-muted p-3">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <span>Why this grade</span>
                <TooltipCopyButton
                  tooltipKey="rankings.whyThisGrade"
                  iconSize="h-3.5 w-3.5"
                  buttonClassName="text-muted-foreground hover:text-foreground"
                />
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{assetDetail.current_grade.grade_explanation}</p>
            </div>
          ) : null}

          <div id="summary-fundamentals" className={anchorClass}>
            <TickerFundamentalsDetails
              latestAsOfDate={fundamentalsLatest?.latest_as_of_date}
              fundamentalsByCode={fundamentalsByCode}
              peIsDerived={peIsDerived}
              pfcfIsDerived={pfcfIsDerived}
              peTtmValue={peTtmValue}
              pfcfValue={pfcfValue}
              hasData={Boolean(fundamentalsLatest)}
              isRedacted={!SHOW_RAW_DATA || Boolean(fundamentalsLatest?.redacted)}
              redactionReason={fundamentalsLatest?.redaction_reason ?? null}
            />
          </div>
          <DataFooter
            asOf={assetDetail.current_grade?.date ?? null}
            source="Internal model"
            cadence="Nightly"
            links={[{ label: 'Methodology', href: '/about/factors' }]}
          />
        </DetailSection>
        ) : null}

        {!isTabbed || activeTab === 'technicals' ? (
        <DetailSection
          id="price"
          title="Price + technicals"
          icon={<BarChart3Icon className="h-4 w-4" aria-hidden />}
          defaultOpen
          subtitle={technicalsLatest?.as_of_date ? `Technicals as of ${formatEasternDate(technicalsLatest.as_of_date)}` : undefined}
        >
          <Top3Grid
            what={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>{rsiDescriptor.label}</div>
                <div>20D return {formatSignedPercent(technicalsLatest?.ret_20d, 1)}</div>
                <div>{macdDescriptor}</div>
              </div>
            }
            why={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>{smaTrendDescriptor}</div>
                <div>ATR14 {formatNumberValue(technicalsLatest?.atr14, 2)}</div>
                <div>Vol Z (20) {formatNumberValue(technicalsLatest?.vol_z20, 2)}</div>
              </div>
            }
            soWhat={
              <span className="text-sm text-foreground">
                {technicalSoWhat}
              </span>
            }
          />

          <div id="technicals-price" className={anchorClass}>
            <StockPriceHistoryCard symbol={normalizedSymbol} />
          </div>
          {!technicalsLatest ? (
            <p className="mt-4 text-sm text-muted-foreground">No technical indicators available for this symbol yet.</p>
          ) : (
            <div id="technicals-indicators" className={`${anchorClass} mt-4 space-y-4`}>
              <TechnicalIndicatorTiles
                rsi={{ value: technicalsLatest.rsi14, data: rsiSpark }}
                macdHist={{ value: technicalsLatest.macd_hist, data: macdHistSpark, maxAbs: macdHistMaxAbs }}
                atr={{ value: technicalsLatest.atr14, data: atrSpark }}
              />

              <TechnicalReadout
                symbol={normalizedSymbol}
                items={technicalReadout}
                atrValue={technicalsLatest?.atr14 ?? null}
              />

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <TechStat label="SMA20" value={formatNumberValue(technicalsLatest.sma20, 2)} />
                <TechStat label="SMA50" value={formatNumberValue(technicalsLatest.sma50, 2)} />
                <TechStat label="SMA200" value={formatNumberValue(technicalsLatest.sma200, 2)} />
                <TechStat label="EMA12" value={formatNumberValue(technicalsLatest.ema12, 2)} />
                <TechStat label="EMA26" value={formatNumberValue(technicalsLatest.ema26, 2)} />
                <TechStat label="BB Upper" value={formatNumberValue(technicalsLatest.bb_upper, 2)} />
                <TechStat label="BB Mid" value={formatNumberValue(technicalsLatest.bb_middle, 2)} />
                <TechStat label="BB Lower" value={formatNumberValue(technicalsLatest.bb_lower, 2)} />
                <TechStat label="RET 5D" value={formatSignedPercent(technicalsLatest.ret_5d, 1)} />
                <TechStat label="RET 20D" value={formatSignedPercent(technicalsLatest.ret_20d, 1)} />
                <TechStat label="RET 60D" value={formatSignedPercent(technicalsLatest.ret_60d, 1)} />
                <TechStat label="RET 120D" value={formatSignedPercent(technicalsLatest.ret_120d, 1)} />
                <TechStat label="VOL Z (20)" value={formatNumberValue(technicalsLatest.vol_z20, 2)} />
                <TechStat label="Dist 52W High" value={formatSignedPercent(technicalsLatest.dist_52w_high, 1)} />
                <TechStat label="MACD" value={formatNumberValue(technicalsLatest.macd, 3)} />
                <TechStat label="MACD Signal" value={formatNumberValue(technicalsLatest.macd_signal, 3)} />
              </div>
            </div>
          )}
          <DataFooter
            asOf={technicalsLatest?.as_of_date ?? null}
            source="Internal model"
            cadence="Nightly"
            links={[{ label: 'Methodology', href: '/methodology' }]}
          />
        </DetailSection>
        ) : null}

        {!isTabbed || activeTab === 'setups' ? (
        <DetailSection
          id="setups"
          title={formatSetupHitsLabel(setupWindowDays)}
          icon={<FilterIcon className="h-4 w-4" aria-hidden />}
          defaultOpen={activeTab === 'setups' || viewVariant !== 'page'}
          subtitle={latestSetupDay?.as_of_date ? `As of ${formatEasternDate(latestSetupDay.as_of_date)}` : `Last ${setupWindowDays}d`}
        >
          <Top3Grid
            what={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>{netLabel}</div>
                <div>{formatSetupHitsLabel(setupWindowDays)}: {windowSetupHits.length}</div>
                <div>{screenBuckets.bullish.length} bullish • {screenBuckets.bearish.length} bearish</div>
              </div>
            }
            why={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>Top bullish: {bullishTop || '-'}</div>
                <div>Top bearish: {bearishTop || '-'}</div>
                <div>Net strength {netStrength || '-'}</div>
              </div>
            }
            soWhat={
              <span className="text-sm text-foreground">
                Review the highest-weight setup hits and confirm with price action before acting.
              </span>
            }
          />

          {windowSetupHits.length === 0 ? (
            <p className="text-sm text-muted-foreground">No setup hits found in the last {setupWindowDays} trading days.</p>
          ) : (
            <div id="setups-hits" className={`${anchorClass} space-y-4`}>
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/screener?symbol=${encodeURIComponent(normalizedSymbol)}&origin=ticker&origin_tab=setups`}
                  className="rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary transition hover:bg-primary/20"
                >
                  Open full setup hits view
                </Link>
                <span className="text-xs text-muted-foreground">
                  {screenBuckets.bullish.length} bullish • {screenBuckets.bearish.length} bearish
                </span>
              </div>

              {screenBuckets.bullish.length ? (
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Bullish setup hits</div>
                  <div className="flex flex-wrap gap-2">
                    {screenBuckets.bullish.slice(0, 18).map((src) => (
                      <Badge
                        key={`bull-${src}`}
                        variant="success"
                        className="px-3 py-1 text-xs"
                      >
                        {formatSetupTag(src, setupWindowDays)}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}

              {screenBuckets.bearish.length ? (
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Bearish setup hits</div>
                  <div className="flex flex-wrap gap-2">
                    {screenBuckets.bearish.slice(0, 18).map((src) => (
                      <Badge
                        key={`bear-${src}`}
                        variant="danger"
                        className="px-3 py-1 text-xs"
                      >
                        {formatSetupTag(src, setupWindowDays)}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}

          <div id="setups-explanation" className={`${anchorClass} mt-4 rounded-xl border border-outline/10 bg-secondary/10 p-3 text-xs text-muted-foreground`}>
            Setup hits are derived from screener rules firing within the last {setupWindowDays} trading days. Net bias reflects the weighted balance of bullish vs bearish hits.
          </div>

          <div id="setups-history" className={`${anchorClass} mt-4`}>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Recent setup history</div>
            {setupDays.length ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {setupDays.slice(0, 4).map((day) => (
                  <div key={day.as_of_date} className="rounded-lg border border-outline/10 bg-card p-3 text-xs">
                    <div className="font-semibold text-foreground">{formatEasternDate(day.as_of_date)}</div>
                    <div className="mt-1 text-muted-foreground">
                      {day.hits.filter((h) => h.bias === 'bullish').length} bullish · {day.hits.filter((h) => h.bias === 'bearish').length} bearish
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">No recent setup history.</div>
            )}
          </div>
        </DetailSection>
        ) : null}

        {!isTabbed || activeTab === 'ai' ? (
          <>
            <DetailSection
              id="ai"
              title="AI Snapshot"
              icon={<BarChart3Icon className="h-4 w-4" aria-hidden />}
              defaultOpen={isTabbed}
              subtitle={aiAsOf ? `As of ${formatEasternDate(aiAsOf)}` : 'As of -'}
            >
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Ticker AI Snapshot (derived from latest AI Memo)
            {aiAsOf ? ` • ${formatEasternDate(aiAsOf)}` : ' • -'}
          </div>
          <div id="ai-snapshot" className={anchorClass}>
            <Top3Grid
            what={
              <div className="space-y-1 text-xs text-muted-foreground">
                {assetDetail.ai_analysis?.news_sentiment_30d != null || assetDetail.ai_analysis?.sentiment_proxy_score != null ? (
                  <>
                    <div>
                      News sentiment 30D {assetDetail.ai_analysis?.news_sentiment_30d ?? '-'}
                    </div>
                    <div>
                      Sentiment proxy {typeof assetDetail.ai_analysis?.sentiment_proxy_score === 'number' ? assetDetail.ai_analysis.sentiment_proxy_score.toFixed(2) : '-'}
                      {assetDetail.ai_analysis?.sentiment_proxy_date ? ` (as of ${formatEasternDate(assetDetail.ai_analysis.sentiment_proxy_date)})` : ''}
                    </div>
                  </>
                ) : (
                  <div>Sentiment unavailable: insufficient coverage</div>
                )}
                <div>Headline buzz {assetDetail.ai_analysis?.headline_buzz || '-'}</div>
              </div>
            }
            why={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>
                  Base {formatUsd(assetDetail.ai_analysis?.scenarios?.base?.price ?? null)}
                  {assetDetail.ai_analysis?.scenarios?.base?.probability_pct !== undefined
                    ? ` (${Number(assetDetail.ai_analysis.scenarios.base.probability_pct).toFixed(0)}%)`
                    : ''}
                </div>
                <div>
                  Bull {formatUsd(assetDetail.ai_analysis?.scenarios?.bull?.price ?? null)}
                  {assetDetail.ai_analysis?.scenarios?.bull?.probability_pct !== undefined
                    ? ` (${Number(assetDetail.ai_analysis.scenarios.bull.probability_pct).toFixed(0)}%)`
                    : ''}
                </div>
                <div>
                  Bear {formatUsd(assetDetail.ai_analysis?.scenarios?.bear?.price ?? null)}
                  {assetDetail.ai_analysis?.scenarios?.bear?.probability_pct !== undefined
                    ? ` (${Number(assetDetail.ai_analysis.scenarios.bear.probability_pct).toFixed(0)}%)`
                    : ''}
                </div>
              </div>
            }
            soWhat={
              <span className="text-sm text-foreground">
                Use the scenario range to frame risk and review catalysts before committing.
              </span>
            }
          />
          </div>

          <div className="space-y-3">
            {assetDetail.ai_analysis ? (
              <Link
                href={aiAnalysisHref}
                className="inline-flex items-center justify-center rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary transition hover:bg-primary/20"
              >
                Open AI Memo
              </Link>
            ) : (
              <span className="inline-flex items-center justify-center rounded-full border border-outline/20 bg-secondary/20 px-3 py-1 text-xs font-semibold text-muted-foreground">
                Open AI Memo
              </span>
            )}
          </div>

          {!assetDetail.ai_analysis ? (
            <div className="mt-3 rounded-xl border border-outline/10 bg-secondary/10 p-3 text-sm text-muted-foreground">
              <div className="font-semibold text-foreground">No AI memo yet for this ticker.</div>
              <p className="mt-1 text-xs">
                Coverage is prioritized for symbols with active screener hits, A/B grades, or meaningful news/earnings.
              </p>
              <div className="mt-2 space-y-1 text-xs">
                <div>Use Momentum/Value scores and setup hits to frame signal strength.</div>
                <div>Check Fundamentals for analyst targets when available.</div>
                <div>Use the Sentiment proxy in the snapshot if present.</div>
              </div>
            </div>
          ) : (
            <div className={`${anchorClass} mt-4`} id="ai-scenarios">
              <div className="rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2 text-xs text-muted-foreground">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-foreground">
                  <span>Scenario probabilities</span>
                  {assetDetail.ai_analysis.overall_rating ? (
                    <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5 text-[10px]">
                      Recommendation: {assetDetail.ai_analysis.overall_rating}
                    </span>
                  ) : null}
                  {assetDetail.ai_analysis.confidence ? (
                    <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5 text-[10px]">
                      Model confidence: {assetDetail.ai_analysis.confidence}
                    </span>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5">
                    Bull Target: {fmtScenarioValue(assetDetail.ai_analysis.scenarios?.bull?.price, assetDetail.ai_analysis.scenarios?.bull?.probability_pct)}
                  </span>
                  <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5">
                    Base Target: {fmtScenarioValue(assetDetail.ai_analysis.scenarios?.base?.price, assetDetail.ai_analysis.scenarios?.base?.probability_pct)}
                  </span>
                  <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5">
                    Bear Target: {fmtScenarioValue(assetDetail.ai_analysis.scenarios?.bear?.price, assetDetail.ai_analysis.scenarios?.bear?.probability_pct)}
                  </span>
                </div>
              </div>

              {assetDetail.ai_analysis.commentary ? (
                <details className="mb-4 rounded-lg border border-outline/10 bg-muted p-4 text-sm text-muted-foreground">
                  <summary className="cursor-pointer font-semibold text-foreground">Commentary</summary>
                  <div className="mt-2 leading-relaxed">{assetDetail.ai_analysis.commentary}</div>
                </details>
              ) : null}

              {(assetDetail.ai_analysis.scenarios?.bull?.price !== undefined ||
                assetDetail.ai_analysis.scenarios?.base?.price !== undefined ||
                assetDetail.ai_analysis.scenarios?.bear?.price !== undefined) && (
                <div className="mb-4">
                  <h4 className="font-semibold mb-2">Scenarios</h4>
                  <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
                    <ScenarioCell label="Bull Target" scenario={assetDetail.ai_analysis.scenarios?.bull} />
                    <ScenarioCell label="Base Target" scenario={assetDetail.ai_analysis.scenarios?.base} />
                    <ScenarioCell label="Bear Target" scenario={assetDetail.ai_analysis.scenarios?.bear} />
                  </div>
                </div>
              )}

              {assetDetail.ai_analysis.analyst_summary ? (
                <div className="mb-4">
                  <h4 className="font-semibold mb-2">Analyst Summary</h4>
                  <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                    <div>
                      <div className="text-xs text-muted-foreground">Bull Case</div>
                      <div className="font-medium">{assetDetail.ai_analysis.analyst_summary.bull_case || '-'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">Bear Case</div>
                      <div className="font-medium">{assetDetail.ai_analysis.analyst_summary.bear_case || '-'}</div>
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="mb-4 grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
                <div id="ai-catalysts" className={anchorClass}>
                  <h4 className="mb-2 font-semibold">Drivers</h4>
                  {aiDrivers.length ? (
                    <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                      {aiDrivers.map((driver, idx) => (
                        <li key={`driver-${idx}`}>{driver}</li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-xs text-muted-foreground">No drivers listed.</div>
                  )}
                </div>
                <div id="ai-risks" className={anchorClass}>
                  <h4 className="mb-2 font-semibold">Risks</h4>
                  {aiRisks.length ? (
                    <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                      {aiRisks.map((risk, idx) => (
                        <li key={`risk-${idx}`}>{risk}</li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-xs text-muted-foreground">No risks listed.</div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
                {assetDetail.ai_analysis.news_sentiment_30d !== undefined ? (
                  <div className="flex flex-col">
                    <span className="text-sm text-muted-foreground">News Sentiment (30D)</span>
                    <span className="font-semibold">{assetDetail.ai_analysis.news_sentiment_30d}</span>
                  </div>
                ) : null}
                {assetDetail.ai_analysis.sentiment_proxy_score !== undefined || assetDetail.ai_analysis.sentiment_proxy_date ? (
                  <div className="flex flex-col">
                    <span className="text-sm text-muted-foreground">Sentiment Proxy</span>
                    <span className="font-semibold">
                      {typeof assetDetail.ai_analysis.sentiment_proxy_score === 'number'
                        ? assetDetail.ai_analysis.sentiment_proxy_score.toFixed(2)
                        : '-'}
                    </span>
                    {assetDetail.ai_analysis.sentiment_proxy_date ? (
                      <span className="text-xs text-muted-foreground">as of {formatEasternDate(assetDetail.ai_analysis.sentiment_proxy_date)}</span>
                    ) : null}
                  </div>
                ) : null}
                {assetDetail.ai_analysis.short_interest_pct ? (
                  <div className="flex flex-col">
                    <span className="text-sm text-muted-foreground">Short Interest</span>
                    <span className="font-semibold">{assetDetail.ai_analysis.short_interest_pct}%</span>
                  </div>
                ) : null}
                {assetDetail.ai_analysis.employee_score ? (
                  <div className="flex flex-col">
                    <span className="text-sm text-muted-foreground">Employee Score</span>
                    <span className="font-semibold">{assetDetail.ai_analysis.employee_score}/5.0</span>
                  </div>
                ) : null}
              </div>

              <div className="mt-4">
                <h4 className="font-semibold mb-2">Sources</h4>
                <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                  {aiSources.map((source, idx) => (
                    <li key={`source-${idx}`}>{source}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          <DataFooter
            asOf={aiAsOf}
            source="Internal model"
            cadence="Nightly"
            links={[{ label: 'Methodology', href: '/about/ai-analysis' }]}
          />
            </DetailSection>

            <DetailSection
              id="events"
              title="Events"
              icon={<CalendarIcon className="h-4 w-4" aria-hidden />}
              defaultOpen={isTabbed}
              subtitle="AI events and headline risks"
            >
          {Array.isArray(assetDetail.ai_analysis?.events) && assetDetail.ai_analysis.events.length > 0 ? (
            <div className="mb-4">
              <h4 className="font-semibold mb-2">AI events</h4>
              <ul className="space-y-2">
                {assetDetail.ai_analysis.events.map((e: any, idx: number) => (
                  <li key={idx} className="rounded-md border border-outline/10 bg-card p-3">
                    <div className="flex items-center justify-between">
                      <div className="font-medium capitalize">{e.catalyst_type || 'event'}</div>
                      {e.expected_date ? <div className="text-xs text-muted-foreground">{e.expected_date}</div> : null}
                    </div>
                    {e.title ? <div className="text-sm mt-1">{e.title}</div> : null}
                    {e.description ? <div className="text-sm text-muted-foreground mt-1">{e.description}</div> : null}
                    <div className="text-xs text-muted-foreground mt-1">
                      {e.probability_pct !== undefined ? <span>Prob {Number(e.probability_pct).toFixed(2)}% · </span> : null}
                      {e.expected_price_move_pct !== undefined ? <span>Move {Number(e.expected_price_move_pct).toFixed(2)}% · </span> : null}
                      {e.priced_in_pct !== undefined ? <span>Priced-in {Number(e.priced_in_pct).toFixed(2)}%</span> : null}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="mb-4 text-sm text-muted-foreground">No AI events listed.</div>
          )}

          <h4 className="font-semibold mb-2">Headline risks</h4>
          {assetDetail.recent_news && assetDetail.recent_news.length > 0 ? (
            <div className="space-y-3">
              {assetDetail.recent_news.map((item, index) => (
                <div key={index} className="flex items-start gap-2 rounded-lg border border-outline/10 bg-card p-3">
                  <div className="flex-1">
                    <h4 className="mb-1 text-xs font-semibold leading-snug">{item.headline}</h4>
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      {item.analysis_date ? <span>Analysis: {formatEasternDate(item.analysis_date)}</span> : null}
                      <Badge variant="danger" className="text-[10px]">
                        Headline Risk
                      </Badge>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">No headline risks identified in recent analysis.</div>
          )}
            </DetailSection>
          </>
        ) : null}

        {!isTabbed || activeTab === 'peers' ? (
        <DetailSection
          id="peers"
          title="Peers"
          defaultOpen={isTabbed}
          subtitle={normalizedPeers.length ? `${normalizedPeers.length.toLocaleString()} peers` : undefined}
        >
          <div id="peers-compare" className={anchorClass}>
            <Top3Grid
            what={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>{normalizedPeers.length} peers tracked</div>
                <div>Grade spread: {peerGradeSpread || '-'}</div>
              </div>
            }
            why={
              <div className="space-y-1 text-xs text-muted-foreground">
                <div>Top peers: {topPeerPreview || '-'}</div>
                <div>Coverage {peerGradeItems.length ? `${peerGradeItems.length} graded` : 'No grades'}</div>
              </div>
            }
            soWhat={
              <span className="text-sm text-foreground">
                Use peers to benchmark relative strength and identify rotation candidates.
              </span>
            }
          />
            <div className="mt-3">
              <Link
                href={compareHref}
                className="inline-flex items-center justify-center rounded-full border border-outline/12 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:border-outline/20 hover:text-foreground"
              >
                Open Compare
              </Link>
            </div>
          </div>

          <div id="peers-list" className={anchorClass}>
            {normalizedPeers.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {normalizedPeers.map(({ peer, normalized }, idx: number) => {
                  const peerSymbol = normalized.display
                  const grade = normalized.lookup
                    .map((candidate) => peerGradeMap[candidate])
                    .find((candidate) => candidate)
                  const content = (
                    <>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold">{peerSymbol || '-'}</span>
                        {grade && grade !== 'N/A' ? (
                          <Badge className={getGradeBadgeColor(grade)}>Grade {grade}</Badge>
                        ) : null}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">{peer?.summary || 'View peer details'}</div>
                    </>
                  )
                  return (
                    <div
                      key={`${peerSymbol || 'peer'}-${idx}`}
                      className="group relative rounded-lg border border-outline/10 bg-card text-sm transition hover:border-outline/16 hover:bg-secondary/15"
                    >
                      {peerSymbol ? (
                        <div className="absolute right-2 top-2 z-10">
                          <CompareCheckbox symbol={peerSymbol} tooltipVariant="compact" />
                        </div>
                      ) : null}
                      {peerSymbol ? (
                        <Link
                          href={`/ticker/${encodeURIComponent(peerSymbol)}`}
                          className="block p-3"
                        >
                          {content}
                        </Link>
                      ) : (
                        <div className="p-3">{content}</div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">No peer data available.</div>
            )}
          </div>
        </DetailSection>
        ) : null}
      </div>
    </div>
  )

  if (viewVariant === 'page') {
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr),240px]">
        <div>{detailContent}</div>
        <aside className="hidden lg:block">
          <div className="sticky top-24">
            <TickerSectionNav groups={navGroups} tabs={tabLinks} />
          </div>
        </aside>
      </div>
    )
  }

  return detailContent
}

function TechStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-outline/10 bg-card p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  )
}

function ScenarioCell({ label, scenario }: { label: string; scenario: any }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-semibold">
        {scenario?.price !== undefined ? `$${Number(scenario?.price).toFixed(2)}` : '-'}
      </div>
      {scenario?.probability_pct !== undefined ? (
        <div className="text-xs text-muted-foreground">Scenario probability {Number(scenario?.probability_pct).toFixed(2)}%</div>
      ) : null}
    </div>
  )
}

function getGradeBadgeColor(grade: string) {
  switch (grade) {
    case 'A':
      return 'bg-status-success-soft text-status-success'
    case 'B':
      return 'bg-status-success/10 text-status-success'
    case 'C':
      return 'bg-status-warning/10 text-status-warning-foreground'
    case 'D':
      return 'bg-status-danger/10 text-status-danger'
    case 'F':
      return 'bg-status-danger-soft text-status-danger'
    default:
      return 'bg-neutralsoft text-foreground'
  }
}
