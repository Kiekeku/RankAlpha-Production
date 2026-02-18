import Link from 'next/link'

import { DocsHeading } from '@/components/docs/docs-heading'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function FactorMethodologyContent({ showInlineToc = true }: { showInlineToc?: boolean }) {
  return (
    <section className="grid grid-cols-1 gap-4">
      <Card className="border-outline/10">
        <CardHeader>
          <CardTitle>Factor Methodology</CardTitle>
          <CardDescription>How Momentum, Value, and Sentiment are produced</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 text-sm leading-relaxed text-muted-foreground">
            {showInlineToc ? (
              <nav aria-label="Factor methodology sections" className="flex flex-wrap gap-2">
                {[
                  { href: '#momentum', label: 'Momentum' },
                  { href: '#value', label: 'Value' },
                  { href: '#sentiment', label: 'Sentiment' },
                  { href: '#composite', label: 'Composite & Grades' },
                ].map((it) => (
                  <a
                    key={it.href}
                    href={it.href}
                    className="rounded-full border border-outline/10 bg-secondary/10 px-3 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                  >
                    {it.label}
                  </a>
                ))}
              </nav>
            ) : null}

            <div className="rounded-xl border border-status-info/25 bg-status-info/10 p-3 text-xs text-status-info-foreground">
              <div className="font-semibold text-status-info-foreground">How this shows up in the product</div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-status-info-foreground/90">
                <li>
                  In <span className="font-semibold">Rankings</span>, Momentum + Value are required for grading eligibility. Sentiment is optional and never penalizes when missing.
                </li>
                <li>
                  In <span className="font-semibold">Stock detail</span>, the Summary tab shows factor scores plus the “Why this grade” explanation.
                </li>
              </ul>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Link href="/rankings" className="rounded-full border border-status-info/25 bg-card px-2.5 py-1 text-[11px] font-semibold text-status-info-foreground hover:underline">
                  See Rankings
                </Link>
                <Link href="/ai-analysis" className="rounded-full border border-status-info/25 bg-card px-2.5 py-1 text-[11px] font-semibold text-status-info-foreground hover:underline">
                  See Sentiment / AI
                </Link>
              </div>
            </div>

            <p>
              The scorer service reads canonical prices and fundamentals, then writes Momentum, Value, and optional Sentiment scores
              into Postgres. Momentum and Value are mandatory for grading eligibility; Sentiment is additive when coverage clears
              quality checks. Scores are scaled to 0–100 before weight blending.
            </p>

            <div className="space-y-2">
              <DocsHeading id="momentum" level={3} className="text-base">Momentum (price trend)</DocsHeading>
              <ul className="list-disc space-y-1 pl-5">
                <li>Input: log Adjusted Close series aligned to the latest trading day with ≥80% coverage in each window.</li>
                <li>Windows: 200/90/50/30 trading days. Fit log-price linear regressions to extract per-day slopes and R².</li>
                <li>
                  Filter out weak fits (R² ≤ 0 or low coverage). Weight remaining slopes by base window weight × (min(|t|, cap)/cap)²
                  using the regression t-statistic (default cap 3.0).
                </li>
                <li>
                  Rank blended slopes cross-sectionally to a 1–100 raw score. Build a sector-neutral residual by subtracting sector
                  medians when the peer group has ≥ the configured minimum (fallback: market median).
                </li>
                <li>Composite momentum = residual × 70% + raw × 30% (defaults; configurable). Raw and residual legs are also stored for diagnostics.</li>
              </ul>
            </div>

            <div className="space-y-2">
              <DocsHeading id="value" level={3} className="text-base">Value (fundamentals, cheaper is better)</DocsHeading>
              <ul className="list-disc space-y-1 pl-5">
                <li>Universe: latest fundamentals within seven calendar days. Peer grouping prefers industry group, falling back to sector.</li>
                <li>
                  Metric buckets: synthetic EV/EBITDA (market cap + net debt over TTM EBITDA), EV/FCF (TTM & annual), Price/FCF,
                  Price/Sales, Price/Book (incl. tangible), P/E, and dividend yield (optional tie-breaker). Financials & Real Estate use
                  sector-specific mixes.
                </li>
                <li>Transform ratios into “cheapness” yields (1/ratio) while keeping direct yields as-is. Winsorize within each metric/peer group; non-positive ratios rank worst.</li>
                <li>Score each metric as 70% peer percentile + 30% market percentile when peer group size ≥5 (configurable). Otherwise, revert to the market percentile.</li>
                <li>Combine available metric buckets with normalized weights, then apply a coverage guardrail (shrink low-coverage scores toward 50) and clip to 0–100.</li>
              </ul>
            </div>

            <div className="space-y-2">
              <DocsHeading id="sentiment" level={3} className="text-base">Sentiment (optional)</DocsHeading>
              <ul className="list-disc space-y-1 pl-5">
                <li>
                  Primary signal: AI scenario proxy (bull/base/bear). Expected return = Σ p<sub>i</sub> × (Target<sub>i</sub>/Price − 1).
                  Probabilities renormalize over available scenarios (default prior 20/60/20).
                </li>
                <li>Fallback: blended news & social sentiment (30-day news, 7-day social) normalized to 0–100.</li>
                <li>Database fallback: if both are missing, use the 30-day news sentiment average scaled via (x + 1) × 50.</li>
                <li>Sentiment is never required. When absent, composite weights re-normalize over Momentum and Value.</li>
              </ul>
            </div>

            <div className="space-y-2">
              <DocsHeading id="composite" level={3} className="text-base">Composite, Weights, Grades</DocsHeading>
              <ul className="list-disc space-y-1 pl-5">
                <li>Weights recompute monthly via Hybrid IC × Risk-Parity using 504-day estimation windows and 21-day forward returns, with shrinkage toward a 0.40/0.40/0.20 baseline.</li>
                <li>Composite score = weighted average over available factors (Momentum + Value required). Missing Sentiment triggers weight re-normalization.</li>
                <li>Composite is ranked cross-sectionally to 1–100. Letter grades: A ≥ 90, B ≥ 70, C ≥ 45, D ≥ 20, else F.</li>
              </ul>

              <div className="mt-3 rounded-xl border border-outline/10 bg-secondary/10 p-3 text-xs text-muted-foreground">
                <div className="font-semibold text-foreground">How this shows up in the product</div>
                <div className="mt-1">
                  In <span className="font-semibold text-foreground">About</span>, the Current Model Weights card shows the live Momentum/Value/Sentiment weights for the latest month.
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </section>
  )
}
