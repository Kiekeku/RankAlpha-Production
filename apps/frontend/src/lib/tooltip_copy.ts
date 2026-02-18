export type TooltipCopyItem = {
  title: string
  body: string
  learnMorePath?: string
}

export const TOOLTIP_COPY = {
  'global.asOf': {
    title: 'Data timestamp',
    body: 'Last refresh time for the scores and dashboards you’re viewing (not necessarily real-time).',
  },
  'global.universe': {
    title: 'Universe',
    body: 'Number of symbols currently tracked after liquidity/price eligibility filters.',
  },
  'global.tickerSearch': {
    title: 'Ticker search',
    body: 'Jump straight to a symbol and open its detail view.',
  },
  'global.views': {
    title: 'Views',
    body: 'Switch layout presets (columns/sections) for this page.',
  },
  'global.share': {
    title: 'Share',
    body: 'Copies a link that preserves your current filters, sort, and page state.',
  },
  'global.resetAll': {
    title: 'Reset all',
    body: 'Clears filters and returns this page to its default state.',
  },
  'global.methodology': {
    title: 'Methodology',
    body: 'How the scores and labels are calculated (definitions + assumptions).',
    learnMorePath: '/about',
  },
  'global.glossary': {
    title: 'Glossary',
    body: 'Quick definitions for platform terms used across dashboards and tables.',
  },
  'table.symbol': {
    title: 'Symbol',
    body: 'Ticker symbol for the security.',
  },
  'table.company': {
    title: 'Company',
    body: 'Issuer name for the security.',
  },
  'table.date': {
    title: 'Date',
    body: 'Effective date for the row.',
  },
  'table.status': {
    title: 'Status',
    body: 'Workflow state for this row.',
  },
  'table.action': {
    title: 'Action',
    body: 'Trade action or operation.',
  },
  'table.price': {
    title: 'Price',
    body: 'Reference price for the action.',
  },
  'table.source': {
    title: 'Source',
    body: 'Originating source for this row.',
  },
  'table.details': {
    title: 'Details',
    body: 'Additional context for the row.',
  },
  'table.type': {
    title: 'Type',
    body: 'Order type and time-in-force.',
  },
  'table.qty': {
    title: 'Qty',
    body: 'Share quantity for the order.',
  },
  'table.seq': {
    title: 'Seq',
    body: 'Sequence index within the run.',
  },
  'table.kind': {
    title: 'Kind',
    body: 'Run type or category.',
  },
  'table.orders': {
    title: 'Orders',
    body: 'Approved vs total order count.',
  },
  'table.model': {
    title: 'Model',
    body: 'Model portfolio name.',
  },
  'table.sleeve': {
    title: 'Sleeve',
    body: 'Sleeve portfolio name.',
  },
  'table.alloc': {
    title: 'Alloc',
    body: 'Allocation percentage for the sleeve.',
  },
  'table.active': {
    title: 'Active',
    body: 'Whether the deployment is active.',
  },
  'table.metric': {
    title: 'Metric',
    body: 'Row label describing the comparison metric.',
  },
  'ai.peers.summary': {
    title: 'Summary',
    body: 'Short AI peer summary for the ticker.',
  },
  'admin.newswire.step': {
    title: 'Step',
    body: 'Pipeline stage for the event.',
  },
  'admin.newswire.timestamp': {
    title: 'Timestamp',
    body: 'Time the pipeline stage was recorded.',
  },
  'admin.newswire.source': {
    title: 'Source / Ticker',
    body: 'Source system and related ticker (if available).',
  },
  'admin.newswire.details': {
    title: 'Details',
    body: 'Raw details captured for the step.',
  },

  'compare.button': {
    title: 'Compare',
    body: 'Build a side-by-side set of up to 3 tickers to evaluate relative strength and targets.',
  },
  'compare.add': {
    title: 'Add to Compare',
    body: 'Adds this ticker to your compare set (max 3).',
  },
  'compare.inCompare': {
    title: 'In Compare',
    body: 'This ticker is already in your compare set.',
  },
  'compare.baseline': {
    title: 'Baseline',
    body: 'Select the reference ticker used for delta comparisons inside Compare.',
  },
  'compare.showDeltas': {
    title: 'Show deltas',
    body: 'Displays differences vs the selected baseline ticker.',
  },
  'compare.absolute': {
    title: 'Absolute',
    body: 'Shows raw values instead of differences vs baseline.',
  },
  'compare.clear': {
    title: 'Clear Compare',
    body: 'Removes all tickers from the compare set.',
  },

  'overview.regime': {
    title: 'Regime',
    body: 'Current market state label derived from cross-asset stress + participation measures.',
  },
  'overview.regime.chop': {
    title: 'Chop',
    body: 'Sideways/mean-reverting conditions where trends are less reliable and signals flip more often.',
  },
  'overview.riskNowcast': {
    title: 'Risk Nowcast',
    body: 'Near-term risk snapshot combining drawdown risk (headline) with cross-asset stress (peripheral).',
    learnMorePath: '/about/nowcast#computation',
  },
  'overview.macroDashboard': {
    title: 'Macro dashboard',
    body: 'Key macro plumbing and stress indicators used to contextualize the current regime.',
  },
  'overview.regimeDetail': {
    title: 'Regime detail',
    body: 'Decomposes the regime into factor rotation, breadth, and style participation measures.',
  },

  'macro.liquidity': {
    title: 'Liquidity',
    body: 'Rule-based read of system liquidity conditions; improving liquidity generally supports risk-taking.',
  },
  'macro.fundingStress': {
    title: 'Funding stress',
    body: 'Funding market tightness proxy (higher = tighter conditions, more stress).',
  },
  'macro.creditStress': {
    title: 'Credit stress',
    body: 'Credit spread stress proxy (wider spreads typically imply higher risk aversion).',
  },
  'macro.vol': {
    title: 'Vol',
    body: 'Volatility level context (higher volatility usually means higher uncertainty and tighter risk budgets).',
  },
  'macro.vrp': {
    title: 'VRP',
    body: 'Volatility Risk Premium: how expensive implied volatility is vs realized (context for hedging/tail pricing).',
  },
  'macro.liquidityVsStress': {
    title: 'Liquidity vs stress',
    body: 'Shows whether liquidity conditions and stress indicators are aligned or in conflict.',
  },

  'regime.styleRotation': {
    title: 'Style rotation',
    body: 'Tracks whether leadership is shifting between Momentum and Value.',
  },
  'regime.marketStructure': {
    title: 'Market structure',
    body: 'Correlation, volatility, and dispersion snapshot that signals tape quality.',
  },
  'regime.fri': {
    title: 'FRI',
    body: 'Factor Rotation Index: positive tends to be momentum-led; negative tends to be value-led.',
  },
  'regime.breadthSpread': {
    title: 'Breadth spread',
    body: 'Share of the universe in top-decile Momentum minus top-decile Value (higher = Momentum leadership).',
  },
  'regime.momentumTenure': {
    title: 'Momentum tenure',
    body: 'Median time leaders stay in the top decile; higher tenure usually means more stable trends.',
  },
  'regime.marketStylesFlow': {
    title: 'Market styles flow',
    body: 'Flow-based regime rules plus breadth-intensity composites.',
  },
  'regime.flowRules': {
    title: 'Flow rules',
    body: 'Rule-based mapping from breadth/participation into style flow signals.',
  },
  'regime.breadthIntensity': {
    title: 'Breadth intensity',
    body: 'How strong and widespread each style’s participation is across the universe.',
  },

  'rankings.grade': {
    title: 'Grade',
    body: 'Composite A–F score from factor components (Momentum + Value, with Sentiment when available).',
    learnMorePath: '/about/factors#composite',
  },
  'rankings.momentumScore': {
    title: 'Momentum',
    body: '0–100 trend strength score (higher = stronger price trend).',
  },
  'rankings.valueScore': {
    title: 'Value',
    body: '0–100 valuation score (higher = cheaper on fundamentals within peers).',
  },
  'rankings.sentimentScore': {
    title: 'Sentiment',
    body: '0–100 sentiment add-on when coverage passes quality checks; otherwise it may be N/A.',
  },
  'rankings.whyThisGrade': {
    title: 'Why this grade',
    body: 'Explains the factor mix and recent changes that produced the current composite grade.',
  },
  'rankings.setups': {
    title: 'Setup hits',
    body: 'Rule-based technical/style screens currently triggering for this ticker.',
  },
  'rankings.setupDuration': {
    title: 'Setup duration',
    body: 'How long the ticker has continuously met the setup conditions.',
  },
  'rankings.aiTargets': {
    title: 'AI Targets',
    body: 'Model price targets with bull/base/bear scenarios and probabilities.',
  },
  'rankings.aiTargetBase': {
    title: 'AI Target (Base)',
    body: 'Base-case price target with probability from the AI model.',
  },
  'rankings.setupHits': {
    title: 'Setup hits',
    body: 'Number of active screener setups over the selected window.',
    learnMorePath: '/about/screeners#section-2-how-we-aggregate-screeners-into-rankings',
  },
  'rankings.setupTag': {
    title: 'Setup tag',
    body: 'Single screener condition currently met. Tags show the setup name plus streak days based on the last window of screener hits (computed nightly).',
    learnMorePath: '/about/screeners#section-2-how-we-aggregate-screeners-into-rankings',
  },

  'chart.priceHistory': {
    title: 'Price history',
    body: 'Adj close history with simple moving averages for trend context.',
  },
  'chart.rsi': {
    title: 'RSI',
    body: 'Relative Strength Index: momentum oscillator where 70+ is overbought and 30- is oversold.',
  },
  'chart.macdHist': {
    title: 'MACD histogram',
    body: 'Momentum gauge showing the gap between MACD and its signal line (positive = bullish momentum).',
  },
  'chart.atr': {
    title: 'ATR',
    body: 'Average True Range: volatility proxy (higher = wider daily ranges).',
  },

  'screener.whatsNew': {
    title: 'What’s new',
    body: 'Symbols that changed status recently (entered, re-entered, or dropped) over the selected window.',
  },
  'screener.window': {
    title: 'Window',
    body: 'Time horizon used to confirm changes (e.g., last 3 trading days).',
  },
  'screener.newEntrants': {
    title: 'New entrants',
    body: 'Symbols that newly qualify for at least one selected screen in the current window.',
  },
  'screener.reEntries': {
    title: 'Re-entries',
    body: 'Symbols that previously qualified, dropped out, and now qualify again.',
  },
  'screener.drops': {
    title: 'Drops',
    body: 'Symbols that no longer qualify for the selected screens.',
  },
  'screener.net': {
    title: 'Net',
    body: 'Net change in qualifying symbols (entrants + re-entries − drops).',
  },
  'screener.clickToTriage': {
    title: 'Triage',
    body: 'Opens the list so you can review the names driving the count.',
  },

  'screener.results.consensusScore': {
    title: 'Consensus',
    body: 'Agreement score across screens/styles; higher means stronger cross-screen confirmation.',
  },
  'screener.results.bestRank': {
    title: 'Best rank',
    body: 'Best (highest) rank the ticker achieves in any triggered screen.',
  },
  'screener.results.bestPercentile': {
    title: 'Best %ile',
    body: 'Best percentile achieved within any triggered screen (0% = top of the list).',
  },
  'screener.results.appearances': {
    title: 'Appear',
    body: 'How frequently the ticker shows up across selected screens in the current view.',
  },
  'screener.results.styles': {
    title: 'Styles',
    body: 'Number of style families currently triggered (more styles = broader confirmation).',
  },
  'screener.results.sources': {
    title: 'Sources',
    body: 'Number of distinct screens contributing evidence for this ticker.',
  },
  'screener.results.primary': {
    title: 'Primary',
    body: 'The strongest single classification driving the ticker’s current screen result.',
  },
  'screener.results.ai': {
    title: 'AI Snapshot',
    body: 'Latest AI snapshot derived from the most recent memo (if available).',
  },
  'screener.results.symbol': {
    title: 'Symbol',
    body: 'Ticker symbol for the security.',
  },
  'screener.results.company': {
    title: 'Company',
    body: 'Issuer name for the selected ticker.',
  },
  'screener.results.style': {
    title: 'Style',
    body: 'Primary style bucket associated with the screen hit.',
  },
  'screener.results.rankDelta': {
    title: 'Rank Δ',
    body: 'Change in screen rank versus the prior observation window.',
  },
  'screener.results.rankNow': {
    title: 'Now',
    body: 'Current rank for the ticker in this screen.',
  },
  'screener.results.rankPrev': {
    title: 'Prev',
    body: 'Previous rank in the prior screen snapshot.',
  },
  'screener.results.driver': {
    title: 'Driver',
    body: 'Primary rule or metric driving the movement.',
  },
  'screener.breadthFlow': {
    title: 'Breadth flow',
    body: 'Daily entrants/drops by style family, signed by bias (risk-on adds, risk-off subtracts).',
    learnMorePath: '/about/screeners#section-2-breadth-and-regime-logic-signed-and-context-aware',
  },
  'screener.breadth.bias': {
    title: 'Bias',
    body: 'Regime bias for the style bucket (bullish/bearish).',
  },
  'screener.breadth.style': {
    title: 'Style',
    body: 'Style family bucket for breadth tracking.',
  },
  'screener.breadth.entrants': {
    title: 'Entrants',
    body: 'Count of symbols entering the style bucket in the latest snapshot.',
  },
  'screener.breadth.drops': {
    title: 'Drops',
    body: 'Count of symbols exiting the style bucket in the latest snapshot.',
  },
  'screener.breadth.net': {
    title: 'Net %',
    body: 'Net flow expressed as a percentage of the universe.',
  },
  'screener.breadth.netAvg': {
    title: 'Net 5d Avg',
    body: 'Five-day average net flow for comparison.',
  },

  'nowcast.riskOffScore': {
    title: 'Risk-off score',
    body: '0–100 scale where higher generally means more stress and higher drawdown risk.',
    learnMorePath: '/about/nowcast#computation',
  },
  'nowcast.whatChanged': {
    title: 'What changed',
    body: 'Day-over-day and week-over-week deltas computed from stored daily snapshots.',
  },
  'nowcast.labels': {
    title: 'Labels',
    body: 'Risk-On / Mixed / Risk-Off buckets derived from the score using fixed thresholds.',
  },
  'nowcast.thresholds': {
    title: 'Thresholds',
    body: 'Default buckets: Risk-Off ≥ 65, Mixed 35–65, Risk-On ≤ 35 (unless configured differently).',
  },

  'aiAnalysis.buySell': {
    title: 'Signal',
    body: 'Direction implied by the scenario-weighted target vs current price (not a guarantee).',
  },
  'aiAnalysis.confidence': {
    title: 'Confidence',
    body: 'Model confidence based on coverage and internal consistency; it is not certainty.',
  },
  'aiAnalysis.bullCase': {
    title: 'Bull',
    body: 'Upside target in the bullish scenario, with an associated weight.',
  },
  'aiAnalysis.baseCase': {
    title: 'Base',
    body: 'Most likely scenario target under normal conditions, with an associated weight.',
  },
  'aiAnalysis.bearCase': {
    title: 'Bear',
    body: 'Downside target in the bearish scenario, with an associated weight.',
  },
  'aiAnalysis.probabilities': {
    title: 'Scenario weights',
    body: 'Weights are model-assigned and sum to 100% across bull/base/bear.',
  },
  'aiAnalysis.nearestBase': {
    title: 'Nearest base',
    body: 'Shows how far the current price is from the base-case target.',
  },
  'aiAnalysis.thesis': {
    title: 'Thesis',
    body: 'The short rationale for the scenario targets (what must be true for upside/downside).',
  },
  'aiAnalysis.catalysts': {
    title: 'Catalysts',
    body: 'Events or drivers that could move the stock toward bull or bear outcomes.',
  },
  'aiAnalysis.risks': {
    title: 'Risks',
    body: 'Key failure modes that would break the thesis or compress the target range.',
  },
  'aiAnalysis.peers': {
    title: 'Peers',
    body: 'Closest comps used for context and relative validation.',
  },
  'aiAnalysis.howComputed': {
    title: 'How computed',
    body: 'Explains the inputs and transformations used to generate targets and confidence.',
  },
} as const satisfies Record<string, TooltipCopyItem>

export type TooltipKey = keyof typeof TOOLTIP_COPY

export function get_tooltip_copy(key: TooltipKey): TooltipCopyItem {
  return TOOLTIP_COPY[key]
}
