'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ClickableCardLink } from '@/components/interaction/clickable_card_link'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ActivityIcon, TrendingUp, BookOpen, Info, Gauge, Network, Sparkles } from 'lucide-react'
import { ContactForm } from '@/components/contact-form'
import { formatEasternDate } from '@/lib/date'
import { PageHero } from '@/components/page-hero'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { DocsSearch } from '@/components/docs/docs-search'
import { InlineError } from '@/components/ui/inline-error'

const NAV_ITEMS = [
  {
    href: '/about/factors',
    title: 'Factor Methodology',
    description: 'Detailed walk-through of Momentum, Value, and Sentiment calculations.',
    icon: TrendingUp,
  },
  {
    href: '/about/nowcast',
    title: 'Risk Nowcast',
    description: 'How the daily Nowcast score and “what changed” deltas are computed.',
    icon: Gauge,
  },
  {
    href: '/about/regime',
    title: 'Regime Detection',
    description: 'How we infer risk‑on/off from screener breadth and intensity.',
    icon: TrendingUp,
  },
  {
    href: '/about/screeners',
    title: 'Screener Methodology',
    description: 'Pre-built screener logic, decays, bonuses, and composite.',
    icon: BookOpen,
  },
  {
    href: '/about/ai-analysis',
    title: 'AI Memos',
    description: 'How AI memos, targets, scenarios, and summaries are generated.',
    icon: Sparkles,
  },
  {
    href: '/about/pipeline',
    title: 'Pipeline Health',
    description: 'Live ingestion, scoring, and sentiment job status plus refresh cadence.',
    icon: ActivityIcon,
  },
  {
    href: '/about/architecture',
    title: 'Architecture Diagram',
    description: 'System overview, components, and data flow at a glance.',
    icon: Network,
  },
]

export default function AboutPage() {
  const { data: weights, isLoading: weightsLoading, isError: weightsError, refetch: refetchWeights } = useQuery({
    queryKey: ['model-weights'],
    queryFn: () => api.getModelWeights(),
    staleTime: 300_000,
  })

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHero
        title="About"
        subtitle="What RankAlpha is, model weights, docs, and contact"
        right={<PrimaryCtaLink href="/methodology">Methodology Overview</PrimaryCtaLink>}
      />

      <section className="grid grid-cols-1 gap-4">
        <Card id="contact">
          <CardHeader>
            <CardTitle>What is RankAlpha</CardTitle>
            <CardDescription>Research-grade factor workflows for a quant audience: Retail quants, Factor investors, Swing traders, Data-driven discretionary. Not meant for day trading nor vibe trading. Not a source for breaking news.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 text-sm leading-relaxed text-muted-foreground">
              <p>
                RankAlpha blends Momentum, Value, and (optionally) Sentiment into a composite 1–100 score and A–F grade.
                The UI is optimized for scan, triage, and drill-down, with clear factor splits, setup hits, and AI summaries.
              </p>
              <p>
                What it is not: personalized investment advice, a brokerage, or a promise of future performance.
                <span className="ml-1">
                  <Link href="/disclaimer" className="font-medium text-primary hover:underline">
                    Read the disclaimer
                  </Link>
                  .
                </span>
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Current Model Weights</CardTitle>
            <CardDescription>Hybrid IC + Risk Parity (monthly)</CardDescription>
          </CardHeader>
          <CardContent>
            {weights ? (
              <div className="space-y-4 text-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant="secondary" className="px-3 py-1 text-xs">
                    As of {formatEasternDate(weights.as_of_date)}
                  </Badge>
                  <Badge variant="secondary" className="px-3 py-1 text-xs">
                    Method: {weights.method}
                  </Badge>
                  <Badge variant="secondary" className="px-3 py-1 text-xs">
                    Source: {weights.source}
                  </Badge>
                  {weights.sentiment_coverage !== null && weights.sentiment_coverage !== undefined && (
                    <Badge variant="model" className="px-3 py-1 text-xs">
                      Sentiment coverage {(weights.sentiment_coverage * 100).toFixed(0)}%
                    </Badge>
                  )}
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  {[
                    { label: 'Momentum', value: weights.w_momentum, tone: 'bg-status-info' },
                    { label: 'Value', value: weights.w_value, tone: 'bg-status-success' },
                    { label: 'Sentiment', value: weights.w_sentiment, tone: 'bg-status-model' },
                  ].map((row) => (
                    <div key={row.label} className="rounded-xl border border-outline/10 bg-secondary/15 p-3">
                      <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        <span>{row.label}</span>
                        <span className="text-foreground">{row.value.toFixed(2)}</span>
                      </div>
                      <div className="mt-2 h-2 w-full rounded-full bg-muted/60">
                        <div
                          className={`h-2 rounded-full ${row.tone}`}
                          style={{ width: `${Math.max(0, Math.min(1, row.value)) * 100}%` }}
                        />
                      </div>
                      <div className="mt-2 text-[11px] text-muted-foreground">{Math.round(row.value * 100)}% weight</div>
                    </div>
                  ))}
                </div>

                <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                  <div className="rounded-lg border border-border/50 bg-muted/40 p-2">
                    Window {weights.window_days}d · Horizon {weights.horizon_days}d
                  </div>
                  <div className="rounded-lg border border-border/50 bg-muted/40 p-2">
                    λ (RP) {weights.lambda_rp.toFixed(2)} · α (shrink) {weights.alpha_shrink.toFixed(2)}
                  </div>
                </div>

                <div className="rounded-xl border border-status-info/25 bg-status-info/10 p-3 text-ds-sm text-status-info-foreground">
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-status-info/15 text-status-info-foreground">
                      <Info className="h-3.5 w-3.5" />
                    </span>
                    <p>
                      <span className="font-semibold text-status-info-foreground">How to read the weights:</span> each bar shows the
                      share of the composite score allocated to that factor this month. Momentum + Value are required;
                      Sentiment is additive when coverage is strong.
                    </p>
                  </div>
                </div>
              </div>
            ) : weightsError ? (
              <InlineError message="Couldn't load model weights." onRetry={() => void refetchWeights()} />
            ) : (
              <div className="space-y-2 text-sm text-muted-foreground">
                {weightsLoading ? (
                  <>
                    <Skeleton className="h-5 w-52" />
                    <div>Loading weights...</div>
                  </>
                ) : (
                  <div>Loading weights...</div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Docs & Methodology</CardTitle>
            <CardDescription>Deep dives on factors, screeners, and ops</CardDescription>
          </CardHeader>
          <CardContent>
            <DocsSearch className="mb-4" />
            <div className="grid gap-3 sm:grid-cols-2">
              {NAV_ITEMS.map((item) => (
                <ClickableCardLink
                  key={item.href}
                  href={item.href}
                  linkClassName="group"
                  className="flex h-full flex-col justify-between rounded-2xl border border-outline/10 bg-secondary/15 p-4 hover:border-outline/16 hover:bg-secondary/22"
                >
                  <div className="flex items-center gap-3">
                    <span className="rounded-full bg-primary/10 p-2 text-primary">
                      <item.icon className="h-4 w-4" />
                    </span>
                    <div>
                      <p className="font-medium text-foreground group-hover:text-primary">{item.title}</p>
                      <p className="text-xs text-muted-foreground">{item.description}</p>
                    </div>
                  </div>
                </ClickableCardLink>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Contact</CardTitle>
            <CardDescription>Questions, feedback, and research requests</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm text-muted-foreground">
              <p className="font-medium text-foreground">Open source</p>
              <p>
                Some data sources and production implementation details are not included in this repo. A sanitized
                public snapshot lives at{' '}
                <Link
                  href="https://github.com/Kiekeku/RankAlpha-Production"
                  className="text-primary hover:underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  Kiekeku/RankAlpha-Production
                </Link>
                .
              </p>
            </div>
            <div className="mt-6">
              <p className="mb-2 text-sm font-medium">For inquiries</p>
              <ContactForm />
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}
