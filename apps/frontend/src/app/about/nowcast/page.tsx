import Link from 'next/link'
import { AlertTriangle, ActivityIcon, Info } from 'lucide-react'

import { DocsHeading } from '@/components/docs/docs-heading'
import { DocsLayout } from '@/components/docs/docs-layout'
import { Card, CardContent } from '@/components/ui/card'

export const metadata = {
  title: 'Risk Nowcast | RankAlpha',
  description: 'How the daily Nowcast translates cross-asset inputs into an equity drawdown risk score.',
}

export default function NowcastPage() {
  return (
    <DocsLayout
      title="Risk Nowcast"
      subtitle="How the daily Nowcast translates cross-asset inputs into an equity drawdown risk score."
      toc={[
        { id: 'overview', label: 'Overview' },
        { id: 'computation', label: 'How it’s computed' },
        { id: 'pillars', label: 'Headline pillars' },
        { id: 'peripheral', label: 'Peripheral signals' },
        { id: 'data', label: 'Data & API' },
      ]}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <section id="overview" className="space-y-3">
        <DocsHeading id="overview" level={2} className="text-2xl">
          Risk Nowcast (Daily)
        </DocsHeading>
        <p className="text-sm text-muted-foreground">Equity drawdown risk (headline) + cross-asset stress (peripheral).</p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Link href="/overview/nowcast" className="rounded-full border border-outline/10 bg-card px-3 py-1 font-semibold text-muted-foreground hover:text-foreground">
            See this metric in Risk Nowcast
          </Link>
          <Link href="/overview/macro" className="rounded-full border border-outline/10 bg-card px-3 py-1 font-semibold text-muted-foreground hover:text-foreground">
            Open Macro Dashboard
          </Link>
        </div>
        <Card>
          <CardContent className="space-y-4 text-sm leading-relaxed text-muted-foreground">
            <div className="flex items-start gap-3 rounded-2xl border border-outline/10 bg-secondary/15 p-3 sm:gap-4 sm:p-4">
              <div className="rounded-full bg-primary/10 p-2 text-primary">
                <ActivityIcon className="h-4 w-4" />
              </div>
              <div className="space-y-1">
                <p className="font-medium text-foreground">What it is</p>
                <p>
                  Nowcast is a daily, dashboard-level synthesis that maps heterogeneous macro and market measures onto a common 0–100
                  <em> risk-off</em> scale. The headline is designed to approximate equity drawdown risk; a separate cross-asset badge
                  provides “plumbing stress” context for tail events.
                </p>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Scale</p>
                <p className="mt-2 text-sm text-foreground">
                  Risk-off score ∈ <span className="font-semibold">[0, 100]</span>
                </p>
                <p className="mt-1 text-xs">Higher = more stress / higher drawdown risk.</p>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">What changed</p>
                <p className="mt-2 text-sm text-foreground">
                  Δ1 trading day · Δ5 trading days
                </p>
                <p className="mt-1 text-xs">Computed from stored nightly snapshots (not client recompute).</p>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Labels</p>
                <p className="mt-2 text-sm text-foreground">
                  Risk-Off / Mixed / Risk-On
                </p>
                <p className="mt-1 text-xs">Thresholds: ≥65, 35–65, ≤35.</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section id="computation" className="space-y-3">
        <DocsHeading id="computation" level={2} className="text-2xl">
          How it’s computed
        </DocsHeading>
        <p className="text-sm text-muted-foreground">Fixed-window standardization + tiered aggregation.</p>
        <Card>
          <CardContent className="space-y-4 text-sm leading-relaxed text-muted-foreground">
            <div className="space-y-2">
              <p className="font-medium text-foreground">Normalization</p>
              <ul className="list-disc space-y-1 pl-5">
                <li>
                  Many inputs are standardized as z-scores using fixed windows (short ≈252 obs, medium ≈756 obs) to avoid “window drift.”
                </li>
                <li>
                  Z-scores are mapped to a 0–100 score using the standard normal CDF: <code>score = 100 × Φ(z)</code>.
                </li>
                <li>Risk-on signals are inverted before mapping (use <code>Φ(−z)</code> or equivalent inversion).</li>
              </ul>
            </div>

            <div className="space-y-2">
              <p className="font-medium text-foreground">Tier weights</p>
              <ul className="list-disc space-y-1 pl-5">
                <li>
                  Tier 1 (Capacity for risk): <span className="font-semibold text-foreground">50%</span>: Liquidity, Vol/Tail
                </li>
                <li>
                  Tier 2 (Cost of risk): <span className="font-semibold text-foreground">30%</span>: Funding, Credit, Rates &amp; USD
                </li>
                <li>
                  Tier 3 (Participation): <span className="font-semibold text-foreground">20%</span>: Breadth, Money Flow
                </li>
              </ul>
              <p className="text-xs">
                Tiers are renormalized over available signals, so missing series don’t mechanically force the score toward 50.
              </p>
            </div>
          </CardContent>
        </Card>
      </section>

      <section id="pillars" className="space-y-3">
        <DocsHeading id="pillars" level={2} className="text-2xl">
          Key pillars (headline)
        </DocsHeading>
        <p className="text-sm text-muted-foreground">Interpretation guide for the PM/quant review.</p>
        <Card>
          <CardContent className="space-y-4 text-sm leading-relaxed text-muted-foreground">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="font-medium text-foreground">Liquidity</p>
                <p className="mt-1 text-xs">
                  Fed plumbing regime (ON RRP / TGA) plus Net Liquidity impulse (WALCL − TGA − RRP) changes. More easing → lower risk-off.
                </p>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="font-medium text-foreground">Vol / Tail (equity)</p>
                <p className="mt-1 text-xs">VIX term structure regime + SKEW (tail insurance demand) standardized to risk-off.</p>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="font-medium text-foreground">Credit</p>
                <p className="mt-1 text-xs">HY OAS z-score. Wider spreads → higher risk-off.</p>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="font-medium text-foreground">Rates &amp; USD</p>
                <p className="mt-1 text-xs">
                  Uses <span className="font-semibold text-foreground">rates shock magnitude</span> (max |Δ5d|, |Δ20d| of 10Y) rather than
                  yield level. Includes curve inversion, real-rate change, and USDX.
                </p>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="font-medium text-foreground">Breadth</p>
                <p className="mt-1 text-xs">SPX target exposure (0..1) mapped to risk-off as (1 − exposure) × 100.</p>
              </div>
              <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4">
                <p className="font-medium text-foreground">Money Flow</p>
                <p className="mt-1 text-xs">Cyclical − defensive risk appetite from sector money-flow scores; inverted to risk-off.</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section id="peripheral" className="space-y-3">
        <DocsHeading id="peripheral" level={2} className="text-2xl">
          Peripheral signals
        </DocsHeading>
        <p className="text-sm text-muted-foreground">Cross-asset stress + “no hiding place” escalation.</p>
        <Card>
          <CardContent className="space-y-4 text-sm leading-relaxed text-muted-foreground">
            <div className="flex items-start gap-3 rounded-2xl border border-status-warning/25 bg-status-warning/10 p-3 sm:gap-4 sm:p-4">
              <div className="rounded-full bg-status-warning/15 p-2 text-status-warning-foreground">
                <AlertTriangle className="h-4 w-4" />
              </div>
              <div className="space-y-1">
                <p className="font-medium text-foreground">Cross-asset stress badge (context-only)</p>
                <p>
                  The badge is meant to surface “plumbing stress” even when equities look calm. It blends Funding + Credit + MOVE and is
                  displayed separately from the headline tier weights.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-outline/10 bg-secondary/15 p-3 sm:gap-4 sm:p-4">
              <div className="rounded-full bg-primary/10 p-2 text-primary">
                <Info className="h-4 w-4" />
              </div>
              <div className="space-y-1">
                <p className="font-medium text-foreground">No-hiding-place booster</p>
                <p>
                  When equity tail risk is elevated and stocks and bonds become positively correlated (both down, corr high), the headline
                  score can be boosted to reflect “no hedge” regimes.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section id="data" className="space-y-3">
        <DocsHeading id="data" level={2} className="text-2xl">
          Where the data comes from
        </DocsHeading>
        <p className="text-sm text-muted-foreground">DB snapshot → API → UI (no client-side recompute).</p>
        <Card>
          <CardContent className="space-y-2 text-sm leading-relaxed text-muted-foreground">
            <ul className="list-disc space-y-1 pl-5">
              <li>
                Nightly snapshots are stored in Postgres tables <code>rankalpha.fact_nowcast_snapshot</code> and{' '}
                <code>rankalpha.fact_nowcast_pillar_snapshot</code>.
              </li>
              <li>
                The API serves the latest snapshot at <code>/api/v1/nowcast/latest</code>; the frontend proxies via{' '}
                <code>/api/nowcast/latest</code>.
              </li>
              <li>
                The UI card on the Home page renders from the snapshot so the “what changed” deltas are reproducible and debuggable.
              </li>
            </ul>
          </CardContent>
        </Card>
      </section>
    </DocsLayout>
  )
}
