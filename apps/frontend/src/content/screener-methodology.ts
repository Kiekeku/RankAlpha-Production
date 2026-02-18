export type MethodologySection = {
  title: string
  intro?: string
  paragraphs?: string[]
  groups?: {
    title: string
    screeners: { name: string; goal: string; criteria: string }[]
  }[]
  subsections?: {
    subtitle: string
    paragraphs?: string[]
    code?: string[]
    bullets?: string[]
  }[]
  bullets?: string[]
  qa?: {
    question: string
    answer: string
  }[]
}

export const methodologyData: MethodologySection[] = [
  {
    title: '1) Screeners by Style (what they hunt & how)',
    intro:
      'Conventions: we enforce basic trading hygiene (stocks only, price and volume floors) inside most presets. Below are the intent and representative criteria (Finviz filters) for each style.',
    groups: [
      {
        title: 'A) Momentum – Breakouts & Continuations',
        screeners: [
          {
            name: 'RA-Momo-50DayBreakout - Fresh 52-Week Breakout (tight)',
            goal: 'Names making new highs with participation (continuation candidates).',
            criteria:
              'New 52-week highs, price above 50/200-DMA, relative volume >= ~1.3-1.5, price >= $10, average volume >= 1M.',
          },
          {
            name: 'RA-Momo-NearHighContinuation - Near-High Continuation (broad)',
            goal: 'Leaders within ~10% of 52-week highs, trend stack (20>50>200).',
            criteria:
              'Within 0-10% of 52-week high, price above 20/50/200-DMA, one-week performance positive.',
          },
          {
            name: 'RA-Momo-Fresh52wBreakout - 50-Day Breakout',
            goal: "Earlier breakouts that haven't printed 52-week highs yet.",
            criteria:
              'New 50-day highs, price above 50/200-DMA, modest relative-volume gate.',
          },
        ],
      },
      {
        title: 'B) Pullback in Uptrend',
        screeners: [
          {
            name: 'RA-Pullback-Under50Over200 - Below 50, Above 200',
            goal: 'Shallow pullbacks in primary uptrends, poised to resume.',
            criteria:
              'Price above 200-DMA and below 50-DMA, price > 20-DMA (or reclaim), RSI not overbought, one-week performance down.',
          },
          {
            name: 'RA-Pullback-ChannelUpWeeklyDown - Channel-Up + Weekly Down',
            goal: 'Touches of lower channel within rising trends.',
            criteria:
              'Pattern = channel up, one-week performance down, price > 200-DMA, RSI roughly 40-55.',
          },
        ],
      },
      {
        title: 'C) Mean-Reversion (oversold bounces)',
        screeners: [
          {
            name: '"RA-MeanReversion-OversoldPop - Oversold Pop',
            goal: 'RSI washout plus relative-volume spike -> bounce candidates.',
            criteria:
              'RSI <= 30, relative volume >= 2, green on the day, price >= $5, average volume >= 1M.',
          },
          {
            name: 'RA-MeanReversion-OversoldUptrend - Oversold but Structural Uptrend',
            goal: 'Oversold within long-term uptrend; less knife-catching.',
            criteria: 'RSI <= 30, price > 200-DMA, moderate relative volume.',
          },
        ],
      },
      {
        title: 'D) Quality Growth (fundamental torque + technical sanity)',
        screeners: [
          {
            name: 'RA-QualityGrowth-EPS - EPS + Sales Acceleration + ROE, Low Leverage',
            goal: 'Real top/bottom-line growth with profitability, not just story.',
            criteria:
              'EPS YoY & next-year growth, sales QoQ growth, ROE > 15%, debt/equity < 1, price > 200-DMA.',
          },
          {
            name: 'RA-QualityGrowth-Trend - Sales + Margins + Trend',
            goal: 'Revenue torque with healthy margins and trend alignment.',
            criteria:
              'Sales QoQ > ~20%, gross margin > ~20%, ROE > 15%, price > 50/200-DMA, RSI >= 50.',
          },
        ],
      },
      {
        title: 'E) Value / GARP / Dividend',
        screeners: [
          {
            name: 'RA-Value-Quality - Quality Value',
            goal: 'Cheaper but healthy balance sheet/business.',
            criteria:
              'P/E <= ~15, PEG low (~<=1), debt/equity < 1, ROE > 12%, price > 200-DMA, mid-cap or larger.',
          },
          {
            name: 'RA-Value-Dividend - Dividend-GARP (Large+)',
            goal: 'Growth-at-reasonable-price among dividend payers.',
            criteria:
              'Dividend > 0, payout ratio < ~60%, P/E <= 20, PEG low, price > 200-DMA, large-cap or larger.',
          },
          {
            name: 'RA-Value-IncomeQuality - Income Quality',
            goal: 'Defensible dividend franchises.',
            criteria:
              'Dividend > 0, payout < ~60%, debt/equity < 1, ROE > 10%, institutional ownership high, price > 200-DMA.',
          },
        ],
      },
      {
        title: 'F) Short-Squeeze Candidates',
        screeners: [
          {
            name: 'RA-ShortSqueeze-OnTheMove - High Short + On the Move',
            goal: 'Crowded shorts where momentum ignition is happening.',
            criteria:
              'Short float high, relative volume >= 1.5, today’s volume >= ~1-2M, often a 50-day breakout.',
          },
          {
            name: '"RA-ShortSqueeze-NearHigh - High Short Near Highs',
            goal: 'Structurally strong, near highs with crowding.',
            criteria:
              'Short float >= ~15%, within 0-10% of 52-week high, liquidity floor enforced.',
          },
        ],
      },
      {
        title: 'G) Earnings Plays',
        screeners: [
          {
            name: 'RA-Earnings-PreSqueeze - Pre-Earnings Squeeze Bias',
            goal: '“Buy the rumor” flows ahead of prints.',
            criteria:
              'Earnings this week, gap up >= ~2%, relative volume >= 1.5, price > 50/200-DMA.',
          },
          {
            name: 'RA-Earnings-PostMomo - Post-Earnings Momentum',
            goal: 'After a strong print, ride continuation leaders.',
            criteria: 'Day/weekly performance up, price > 50/200-DMA.',
          },
        ],
      },
      {
        title: 'H) IPO Momentum',
        screeners: [
          {
            name: 'RA-IPO-Momo - Young + Ripping',
            goal: 'Recent IPOs with real sales torque making highs.',
            criteria:
              'IPO <= 3 years, sales QoQ > ~30%, new 52-week high, relative volume >= 2.',
          },
        ],
      },
      {
        title: 'I) Defensive Quality / Low-Vol',
        screeners: [
          {
            name: 'RA-Quality-LowBeta - Low Beta Compounders',
            goal: 'Ballast: steady return of capital/returns on capital.',
            criteria:
              'Large-cap or larger, beta < ~0.9, debt/equity < 1, ROE > 12%, price > 200-DMA.',
          },        
        ],
      },
      {
        title: 'J) Short / Sell-Bias',
        screeners: [
          {
            name: 'RA-Short-MomoBreakdown - Momentum Breakdown',
            goal: 'Structural downtrends with fresh weakness.',
            criteria: 'Price < 50-DMA and < 200-DMA, new 20-day lows, relative volume >= 1.5.',
          },
          {
            name: 'RA-Short-Resistance - Overbought Fade into Resistance',
            goal: 'Stretched rallies into nearby supply.',
            criteria: 'RSI >= 70, within 0-5% below 20-day high, down on the day.',
          },
        ],
      },
    ],
  },
  {
    title: '2) How We Aggregate Screeners into Rankings',
    intro:
      'We do not rely on fragile fundamentals or external calendars at scoring time. Instead, we only need membership: did a symbol appear in a given screener today?',
    subsections: [
      {
        subtitle: '2.1 Daily inputs',
        paragraphs: [
          'Each screener belongs to a style (family) and has a tier/weight: source_weight ∈ {1.2, 1.0, 0.8} with style_weight ≥ 0; every style is tagged long/short.',
          'We record one row per (symbol, screener) for the latest trading day. For consensus we use weights, not raw counts: appearances = Σ(style_weight × source_weight) over hits; styles_distinct and sources_distinct are weight-summed over distinct styles/sources (sum of the max weight per distinct key). Inactive stocks and excluded sources are filtered out.',
        ],
      },
      {
        subtitle: '2.2 Per-style contribution (concise)',
        paragraphs: [
          'Within each style for a symbol, we sort that symbol’s hits and apply a diminishing-returns decay across the first five hits; later hits contribute 0. This rewards the first few confirmations and then tapers.',
        ],
        code: [
          'decay δ = [1.00, 0.70, 0.50, 0.35, 0.25]  (cap at 5 per style)',
          'style_score = style_weight × Σ_k (δ_k × source_weight_k)',
        ],
      },
      {
        subtitle: '2.3 Portfolio-friendly bonuses',
        bullets: [
          'Reinforcement (+1, once): if a symbol hits ≥ 2 screens within any one long style, add +1 globally. This rewards in-style consensus without letting it explode.',
          'Breadth (0 to +1.5): +0.5 × (distinct long styles − 1), capped at +1.5. This rewards cross-style confirmation.',
        ],
      },
      {
        subtitle: '2.4 Streak overlay (side-specific)',
        bullets: [
          'Any-streak: +0.1 per day a symbol appears in any long style (cap +0.5). Short side is separate and only counts Short style days.',
          'Family-streak: sum of min(+0.5, 0.1 × consecutive days) across long styles (cap +1.0) and Short (cap +0.5).',
        ],
      },
      {
        subtitle: '2.5 Final scores & percentiles',
        paragraphs: [
          'LongScore = sum of all long style_scores + reinforcement + breadth + long streak bonuses.',
          'ShortScore = Short style_score + short streak bonuses.',
          'NetScore = LongScore − ShortScore.',
          'For presentation, we compute percentiles per side (long over names with LongScore > 0, etc.) so the UI is stable day-to-day.',
        ],
      },
      {
        subtitle: '2.6 Consensus composite (0–100)',
        paragraphs: [
          'The daily consensus_score blends a placement/coverage base with the decay-based Long/Short/Net leg, then clips to [0,100]. The base uses the best style percentile and weighted coverage:',
        ],
        code: [
          'base = (100 × (1 − min_style_rank_pct)) + 10 × ln(1 + appearances) + 5 × styles_distinct + 5 × sources_distinct',
          'if long-side:  consensus = base + 12 × LongScore + 6 × max(NetScore, 0) − 6 × max(ShortScore, 0)',
          'if short-side: consensus = base + 12 × ShortScore + 6 × max(−NetScore, 0) − 6 × max(LongScore, 0)',
          'consensus_score = clamp(round(consensus, 2), 0, 100)',
        ],
        bullets: [
          'Counts above are weight-summed (see 2.1).',
          'Placement percentile and coverage are derived from membership/ranks only (no external fundamentals).',
        ],
      },
    ],
  },
  {
    title: '2) Breadth & Regime logic (signed + context-aware)',
    subsections: [
      {
        subtitle: 'Signed breadth (Bullish vs Bearish styles)',
        paragraphs: [
          'Raw breadth treats every style the same, which is misleading for risk‑off styles (Short, MeanReversion, Defensive, EarningsPre). We sign breadth by style bias so risk‑off strength subtracts from aggregate breadth while risk‑on strength adds to it.',
          'The API exposes signed fields so clients don\'t need to re‑implement logic: regime_bias (Bullish/Bearish), net_pct_signed, and net_pct_avg_5d_signed. The UI\'s “Net breadth” uses a universe‑weighted average of the signed percentages.'
        ],
        code: [
          'For each style i on day t:',
          '  net_pct_i(t) = (entered_i − dropped_i) / eligible_i',
          '  sign_i = +1 for Bullish styles; −1 for Bearish',
          '  net_pct_signed_i(t) = sign_i × net_pct_i(t)',
          '',
          'Weighted aggregate (recommended):',
          '  NetBreadth(t) = Σ_i [ net_pct_signed_i(t) × eligible_i(t) ] / Σ_i eligible_i(t)',
        ],
      },
      {
        subtitle: 'Dynamic Pullback regime weight',
        paragraphs: [
          'Pullbacks are bullish when they reflect buy‑the‑dip within healthy breakout regimes, but can signal distribution when breakouts stall and stress rises. We adjust Pullback\'s regime weight daily using the breakout–pullback spread and a stress overlay from risk‑off styles.',
        ],
        code: [
          'Z_momo(t), Z_pull(t), Z_mr(t), Z_short(t) - standardized style intensities',
          'Δ(t) = Z_momo(t) − Z_pull(t)',
          'Stress(t) = max(0, 0.5·Z_mr(t) + 0.5·Z_short(t))',
          'g(t) = tanh(Δ/0.75) − 0.3·max(0, Stress − 0.25)   ∈ [−1, +1]',
          'w_pull,eff(t) = w_pull,base × g(t)',
        ],
        bullets: [
          'When Momentum leads and stress is low → g > 0 (Pullback contributes positively).',
          'When Pullback dominates and stress is elevated → g < 0 (Pullback attenuates or flips negative).',
          'Effective weights are persisted and exposed via the API for transparency.',
        ],
      },
      {
        subtitle: 'Flow-based regime rules (Trend / Chop / Risk-Off)',
        paragraphs: [
          'In addition to the legacy intensity cores, we now track daily “flows” for every canonical style: entrants, exits, continuers, churn, and transition bias (Pullback → Momentum vs Pullback → Short). We normalize each series by the eligible US universe and apply robust rolling Z-scores (MAD/IQR guarded) over 126d/252d windows so the signals are comparable over time.',
          'Those flow Z-scores roll up into compact composites: Momo Breadth (MB), Breakdown Breadth (BB), Mean-Reversion Intensity (MRI), Defensive Breadth (DB), Trend Thrust (TT), Mean-Reversion Pressure (MRP), Risk-Off Pressure (ROP), and Defensive Tilt (DT). A persistence score (PS) compares continuers in trend vs. MR/Short styles, while Transition Bias (TB) looks at how pullbacks resolve on the next session.'
        ],
        code: [
          'RS = w_mb·MB + w_bb·BB + w_mri·MRI + w_db·DB   (default weights: +1.0, −0.9, −0.4, −0.5)',
          'RS_smooth = rolling_mean(RS, hysteresis_days≈3)',
          'Labels: Trend if RS_smooth > +0.5 for ≥3 days; Risk-Off if RS_smooth < −0.5 for ≥3 days; else Chop (tagged MeanReversionFavored when MRI > 0).',
          'Tags: DefensiveDrift when Defensive flows sit in the 80th pct while MB < 0; SpeculativeMania when Squeeze + IPO flows spike into the 90th pct.',
          'Persistence veto: if PS < 0, cap RS at +0.25 to avoid false Trend readings during choppy tapes.',
        ],
        bullets: [
          'Outputs live in rankalpha.fact_regime_rules and are exposed via `GET /api/v1/screener/regime-rules/latest` (plus `/series`).',
          'The UI can show both regimes side-by-side: intensity cores for structure, flow rules for faster turn detection and tags.',
          'All flow inputs respect the same eligibility policy as consensus (Close ≥ $10, AvgVol63d ≥ 1M, major U.S. listings), so secular listing growth doesn’t bias readings.',
        ],
      },
    ],
  },
  {
    title: '3) How to read the leaderboard (for investors)',
    bullets: [
      'LongScore / long percentile: higher -> more aligned with our investable definitions of leadership (momentum, quality growth, value/GARP where applicable) with volume/liquidity embedded in the screeners.',
      'ShortScore / short percentile: higher -> stronger sell-bias characteristics (breakdowns, exhaustion).',
      'NetScore: quick read across both.',
      'Repeated appearances across different styles are intentional; they increase conviction.',
      'Not a crystal ball: this signal stack is designed to improve odds and behavior, not provide guarantees. It systematically elevates liquid, institutionally holdable trends and down-weights speculative noise.',
    ],
  },
  {
    title: '4) Data pipeline & governance (one-pager)',
    paragraphs: [
      'Collection: Each screener emits today’s symbol hits, loaded into a partitioned fact table (fact_screener_rank).',
      'Dimensions: dim_style (style, side, weight) and dim_source (screener, weight, opt-out) configure the system without code changes.',
      'Views: v_latest_screener_values exposes today’s hits with weights; v_latest_screener_consensus provides an enriched composite used by the API.',
      'API: /api/v1/screener/consensus returns daily aggregates including Long/Short/Net + percentiles for presentation.',
    ],
  },
  {
    title: '5) FAQ for semi-quants',
    qa: [
      {
        question: 'Why tiers?',
        answer: 'To encode difficulty/selectivity (e.g., fresh 52-week breakouts are harder than near-highs).',
      },
      {
        question: 'Why decay?',
        answer: 'To avoid over-rewarding six variants of the same signal; the first confirmations matter most.',
      },
      {
        question: 'Why breadth?',
        answer: 'Different styles interrogate a stock from different angles; cross-style alignment is rarer and more durable.',
      },
      {
        question: 'What about liquidity and price floors?',
        answer:
          'Those are enforced inside the screens themselves (e.g., price >= $10, average volume >= 1M), so we do not need extra penalties later.',
      },
      {
        question: 'What if a screen’s definition changes?',
        answer:
          'It is just a source with a weight and tier; the scoring math does not change. Update the definitions and weights, and the scores adapt.',
      },
    ],
  },
] as const
