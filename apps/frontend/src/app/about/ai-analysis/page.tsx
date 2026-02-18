import type { Metadata } from 'next'

import Link from 'next/link'
import { AlertTriangle } from 'lucide-react'

import { DocsHeading } from '@/components/docs/docs-heading'
import { DocsLayout } from '@/components/docs/docs-layout'

export const metadata: Metadata = {
  title: 'AI Memos | RankAlpha',
  description: 'How RankAlpha generates AI memos, targets, scenarios, confidence, and narrative summaries.',
}

export default function AiAnalysisPage() {
  return (
    <DocsLayout
      title="AI Memos"
      subtitle="How AI memos, targets, scenarios, and summaries are generated."
      toc={[
        { id: 'overview', label: 'Overview' },
        { id: 'inputs', label: 'Inputs' },
        { id: 'outputs', label: 'Outputs' },
        { id: 'quality', label: 'Quality & limits' },
        { id: 'cadence', label: 'Refresh cadence' },
      ]}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <section id="overview" className="space-y-3">
        <DocsHeading id="overview" level={2} className="text-2xl">
          Overview
        </DocsHeading>
        <div className="flex items-start gap-3 rounded-2xl border border-status-warning/25 bg-status-warning/10 p-3 sm:gap-4 sm:p-4">
          <div className="rounded-full bg-status-warning/15 p-2 text-status-warning-foreground">
            <AlertTriangle className="h-4 w-4" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-semibold text-status-warning-foreground">Experimental feature</p>
            <p className="text-sm text-status-warning-foreground/90">
              AI Memos are experimental and may change without notice. Use them as research context, not a guarantee.
            </p>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          AI Memos are a research memo layer that combines structured signals (price, factors, fundamentals, risk)
          with model-guided narrative synthesis. It produces scenario-based price targets (bull/base/bear), a confidence
          estimate, and a compact thesis. The goal is speed and consistency, not certainty.
        </p>
        <div className="rounded-2xl border border-outline/10 bg-secondary/15 p-4 text-sm text-muted-foreground">
          <div className="font-semibold text-foreground">How to read it</div>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>Targets are scenario-weighted (not a single-point forecast).</li>
            <li>Confidence is about data coverage + internal consistency, not a probability of being “right.”</li>
            <li>Use the memo alongside Momentum/Value signals and setup hits for triage.</li>
          </ul>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Link
            href="/ai-analysis"
            className="rounded-full border border-outline/10 bg-card px-3 py-1 font-semibold text-muted-foreground hover:text-foreground"
          >
            Open AI Feed
          </Link>
          <Link
            href="/ticker"
            className="rounded-full border border-outline/10 bg-card px-3 py-1 font-semibold text-muted-foreground hover:text-foreground"
          >
            Open Ticker Detail
          </Link>
        </div>
      </section>

      <section id="inputs" className="space-y-3">
        <DocsHeading id="inputs" level={2} className="text-2xl">
          Inputs
        </DocsHeading>
        <p className="text-sm text-muted-foreground">
          Inputs are sourced from point‑in‑time fundamentals and fresh market context. The system anchors scenarios to
          a real observed price at the time of analysis, then enriches with filings and news.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>EDGAR filings for financial statements, fundamentals, and narrative context.</li>
          <li>Point‑in‑time market price used as the anchor for all target deltas.</li>
          <li>Serper (Google search) for recent news and sentiment signals.</li>
          <li>Human analyst price targets (via Serper) used as external anchors and sanity checks.</li>
        </ul>
      </section>

      <section id="outputs" className="space-y-3">
        <DocsHeading id="outputs" level={2} className="text-2xl">
          Outputs
        </DocsHeading>
        <p className="text-sm text-muted-foreground">
          Output is a memo snapshot tied to a specific analysis date. The UI presents both a compact summary and a
          full-detail memo view.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Scenario targets (Bull / Base / Bear) with probabilities.</li>
          <li>AI Target (Base) used across Rankings and Compare.</li>
          <li>Confidence label and rating context where available.</li>
          <li>Key drivers, catalysts, and risks (structured lists + narrative).</li>
          <li>Peer references and data gaps when coverage is partial.</li>
        </ul>
        <div className="mt-2 text-xs text-muted-foreground">
          Terminology: <span className="font-semibold text-foreground">AI Feed</span> = latest memos across screened companies;
          <span className="font-semibold text-foreground"> AI Snapshot</span> = latest memo summary for one symbol;
          <span className="font-semibold text-foreground"> AI Memo</span> = longform memo for a specific date.
        </div>
      </section>

      <section id="quality" className="space-y-3">
        <DocsHeading id="quality" level={2} className="text-2xl">
          Quality &amp; limits
        </DocsHeading>
        <p className="text-sm text-muted-foreground">
          AI memos are designed to be consistent and auditable, but they are not a guarantee. Treat them as a
          research aid.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Coverage varies by symbol; some fields can be missing or stale.</li>
          <li>Events/catalysts are best-effort summaries and may omit hard-to-parse disclosures.</li>
          <li>Model narratives can reflect noisy inputs; always confirm with primary sources.</li>
          <li>Risk labels and confidence are qualitative summaries of data consistency, not a forecast.</li>
        </ul>
      </section>

      <section id="cadence" className="space-y-3">
        <DocsHeading id="cadence" level={2} className="text-2xl">
          Refresh cadence
        </DocsHeading>
        <p className="text-sm text-muted-foreground">
          AI memos run on a focused universe: symbols that hit a setup/screener or hold a current A/B rank.
          For those names, memos refresh bi‑weekly or shortly after earnings. If a memo is missing for a
          symbol/date, the UI falls back to the latest available snapshot.
        </p>
      </section>
    </DocsLayout>
  )
}
