import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { DocsHeading } from '@/components/docs/docs-heading'
import { DocsLayout } from '@/components/docs/docs-layout'

export const metadata = {
  title: 'Regime Detection | RankAlpha',
  description: 'How we infer risk‑on / risk‑off from screener breadth and intensity.',
}

export default function RegimePage() {
  return (
    <DocsLayout
      title="Regime Detection"
      subtitle="How we translate screener breadth into a market-state signal."
      toc={[
        { id: 'regime-detection', label: 'Regime Detection' },
        { id: 'rank-regime', label: 'Rank Regime (Momentum ↔ Value)' },
      ]}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <section id="regime-detection" className="space-y-3">
        <DocsHeading id="regime-detection" level={2} className="text-2xl">
          Regime Detection
        </DocsHeading>
        <p className="text-sm text-muted-foreground">How we translate screener breadth into a market-state signal.</p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Link href="/overview/regime" className="rounded-full border border-outline/10 bg-card px-3 py-1 font-semibold text-muted-foreground hover:text-foreground">
            See Regime Dashboard
          </Link>
          <Link href="/screener" className="rounded-full border border-outline/10 bg-card px-3 py-1 font-semibold text-muted-foreground hover:text-foreground">
            Explore Screeners
          </Link>
        </div>
        <Card>
          <CardContent>
            <div className="space-y-4 text-sm leading-relaxed text-muted-foreground">
              <div className="space-y-2">
                <p className="font-medium text-foreground">What we measure</p>
                <p>
                  Regime is a backdrop indicator. It rises when risk-on styles like Momentum, Pullback-in-Uptrend, and Quality Growth show broad, repeated participation across the investable universe, and falls when risk-off styles like Short, Mean-Reversion, and Defensive dominate. We aim to capture participation and leadership quality, not predict prices outright.
                </p>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Daily inputs</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li><strong>Universe U(t):</strong> US-listed common stocks (incl. ADRs) that meet price & liquidity floors on day t (Close ≥ $10, AvgVol 3m ≥ 1M, ≥15/22 bars, listed on NYSE/NASDAQ/AMEX/CBOE).</li>
                  <li><strong>Style hits:</strong> Each screener maps to a style family (Momentum, Pullback, QualityGrowth, ValueGARP, IPO, EarningsPre/Post, Squeeze, Short, MeanRev, Defensive). Each hit carries a tier {`{1.2, 1.0, 0.8}`} reflecting selectivity.</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">From hits to intensity</p>
                <ol className="list-decimal space-y-1 pl-5">
                  <li><strong>Per symbol/style:</strong> take the day’s <em>max</em> tier (avoid over-counting near duplicates).</li>
                  <li><strong>Style intensity:</strong> sum those max tiers across symbols and divide by U(t). Result: normalized “breadth × strength.”</li>
                  <li><strong>Zero-floor:</strong> quiet styles produce 0.0, so every canonical style remains in the calculation.</li>
                </ol>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Robust standardization</p>
                <p>
                  Intensities are standardized per style using rolling medians and MAD/IQR scales (≈252 trading days, fallback 90). This puts growth, value, momentum, etc. on a comparable yardstick and limits noise. Z-scores clip to ±4.
                </p>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Risk-On vs Risk-Off cores</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li><strong>Risk-On:</strong> Momentum (1.0), Pullback (0.6), QualityGrowth (0.9), ValueGARP (0.4), IPO (0.5), EarningsPost (0.6), Squeeze (0.3).</li>
                  <li><strong>Risk-Off:</strong> Short (1.0), MeanRev (0.6), Defensive (0.5), EarningsPre (0.3).</li>
                </ul>
                <p>
                  RiskOnCore = Σ w<sub>f</sub>·Z<sub>f</sub> over the Risk-On set. RiskOffCore analogous. Raw regime = RiskOnCore − RiskOffCore.
                </p>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Smoothing, labels, index</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li><strong>Smoothing:</strong> EMA<sub>10</sub> (tactical) and EMA<sub>50</sub> (structural) over the raw regime.</li>
                  <li><strong>Hysteresis:</strong> Risk-On if EMA<sub>10</sub> &gt; +0.5 for 3 days; Risk-Off if &lt; −0.5 for 3 days; else Neutral.</li>
                  <li><strong>Index (0–100):</strong> 50 + 10 × z-score(EMA<sub>10</sub> vs last 252 days), clipped to [0, 100].</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">How to read it</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li>Rising regime + strong Momentum/QualityGrowth breadth → healthy risk appetite.</li>
                  <li>Falling regime + Short/Defensive dominance → distribution/risk aversion.</li>
                  <li>Divergences (Momentum Z − MeanRev Z) often flag rotations before the headline flips.</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Design principles</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li><strong>Point-in-time:</strong> daily universe is as-of each date (no survivorship bias).</li>
                  <li><strong>Parsimony:</strong> max-tier deduping rewards the first confirmations without inflating clones.</li>
                  <li><strong>Robustness:</strong> median/MAD scaling + hysteresis reduce whipsaw.</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Practical notes</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li>Use regime as context and sizing input, not a standalone signal.</li>
                  <li>Quiet risk-on days may show lower scores simply because leadership narrowed; that’s intentional.</li>
                  <li>An optional participation overlay (RVOL-gated Momentum/Pullback) boosts confidence or signals fragility.</li>
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section id="rank-regime" className="space-y-3">
        <DocsHeading id="rank-regime" level={2} className="text-2xl">
          Rank Regime (Momentum ↔ Value Migration)
        </DocsHeading>
        <p className="text-sm text-muted-foreground">Factor-level rotation using rank flows between Momentum and Value.</p>
        <Card>
          <CardContent>
            <div className="space-y-4 text-sm leading-relaxed text-muted-foreground">
              <div className="space-y-2">
                <p className="font-medium text-foreground">What we measure</p>
                <p>
                  A clean, interpretable view of style leadership based on daily movements between the top Momentum and top Value rank buckets.
                  When Value names migrate into the Momentum top decile faster than the reverse, a trend‑led, risk‑on environment is forming; the opposite favors repair/mean‑reversion.
                </p>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Inputs & Universe</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li><strong>Scores:</strong> Daily Momentum and Value percentiles in [0–100] from our scorer (sector‑aware).</li>
                  <li><strong>Top buckets:</strong> Momentum top decile M(t) = percentile ≥ 90; Value top decile V(t) = percentile ≥ 90.</li>
                  <li><strong>Universe U(t):</strong> Liquid, active equities only (common + ADRs) using our eligibility policy; flows computed on U(t−1) ∩ U(t) to avoid eligibility artifacts.</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Construction</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li><strong>Migration:</strong> Val→Mom(t) = |(V(t−1) \ M(t−1)) ∩ M(t)| / |U(t)|; Mom→Val defined symmetrically. Smooth each with a 10‑day simple moving average (SMA) and z‑score over 252d (note: SMA is slower than EMA by design).</li>
                  <li><strong>FRI (Factor Rotation Index):</strong> FRI<sub>z</sub>(t) = z(Val→Mom) − z(Mom→Val). Optional log‑odds shown as telemetry.</li>
                  <li><strong>Breadth:</strong> Momentum/Value breadth = |M(t)|/|U(t)|, |V(t)|/|U(t)|; spread = MB − VB.</li>
                  <li><strong>Tenure & Hazard:</strong> Median consecutive days in M(t) (tenure); exit rate from M(t−1) (hazard). Rising tenure with positive FRI indicates cleaner trends.</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Daily outputs</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li>FRI<sub>z</sub> (primary), FRI<sub>log</sub> (secondary)</li>
                  <li>Momentum/Value breadth and spread</li>
                  <li>Median Momentum tenure and hazards</li>
                  <li>Label + confidence</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Labels & Hysteresis</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li><strong>Momentum‑led:</strong> FRI<sub>z</sub> ≥ +0.5 and rising; lower Momentum hazard.</li>
                  <li><strong>Value‑led:</strong> FRI<sub>z</sub> ≤ −0.5 and falling; elevated Momentum hazard.</li>
                  <li><strong>Transition:</strong> Otherwise; breadth spread near 0, higher churn.</li>
                  <li><strong>Stress:</strong> Any two of: top‑bucket turnover in top decile, high hazards, extreme dispersion, |FRI<sub>z</sub>| ≤ 0.3. Stress takes precedence.</li>
                  <li><strong>Anti‑flicker:</strong> 2‑day confirmation to enter Momentum‑led / Value‑led; Stress uses 2‑of‑3 days rule.</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">How to read it</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li>Positive, rising FRI with rising M‑tenure → trend leadership broadening (risk‑on).</li>
                  <li>Negative FRI with elevated hazards → value‑led repair, chop likely.</li>
                  <li>Stress label + high turnover/hazards → fragile/transitionary tape; down‑weight breakout attempts.</li>
                </ul>
              </div>

              <div className="space-y-2">
                <p className="font-medium text-foreground">Operational notes</p>
                <ul className="list-disc space-y-1 pl-5">
                  <li>Computed daily after US close; exposed via API at <code>/api/v1/signals/rank-regime</code> and shown under Rankings → Regime.</li>
                  <li>Universe and buckets are point‑in‑time; symbol coverage requires ≥252 trading days for stable z‑scores.</li>
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>
    </DocsLayout>
  )
}
