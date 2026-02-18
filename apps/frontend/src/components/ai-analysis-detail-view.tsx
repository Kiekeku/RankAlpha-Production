'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { SparklesIcon } from 'lucide-react'
import { AiAnalysisItem, HumanAnalystTargetOrganicItem } from '@/lib/api'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { DataTable } from '@/components/ui/data-table'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/page-header'
import { PrimaryBackLink } from '@/components/primary-back-link'
import { TabAnchor, TabNav } from '@/components/ui/tab-nav'
import { DataFooter } from '@/components/data-footer'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { formatEasternDate } from '@/lib/date'
import { ColumnHeaderTooltip } from '@/components/column-header-tooltip'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { RedactedOverlay } from '@/components/ui/redacted'
import { computeHumanTargetBucket } from '@/lib/human_targets'
import { TickerSectionNav } from '@/components/ticker/ticker-section-nav'
import { DataFreshnessBar, type DataFreshnessItem } from '@/components/data/data-freshness-bar'
import { useToast } from '@/components/ui/use-toast'
import {
  computePct,
  fmtBullBearSpread,
  fmtPctSigned,
  fmtPriceTarget,
  fmtProbability,
  getHumanTargetBucketMeta,
} from '@/lib/ai_analysis_format'

export function AiAnalysisDetailView({ analysis }: { analysis: AiAnalysisItem }) {
  const { toast } = useToast()
  const asOf = formatEasternDate(analysis.as_of_date)
  const headerContextBadges = [
    asOf ? `As of ${asOf}` : null,
    analysis.confidence ? `Confidence ${analysis.confidence}` : null,
    analysis.recommendation_timeframe ? `Horizon ${analysis.recommendation_timeframe}` : null,
  ].filter(Boolean)
  const riskItems = [
    ...(analysis.headline_risks ?? []),
    ...(analysis.macro_risks ?? []),
    ...(analysis.data_gaps ?? []),
  ]
  const drivers = extractDrivers(analysis)
  const sources = buildSources(analysis)
  const keyBullets = buildKeyBullets(analysis)
  const humanTargetBucket = analysis.human_target_vs_ra || computeHumanTargetBucket(analysis)
  const humanTargetMeta = getHumanTargetBucketMeta(humanTargetBucket)
  const hasHumanTargets =
    Boolean(humanTargetBucket) ||
    analysis.human_analyst_target_count != null ||
    (analysis.human_analyst_targets_organic && analysis.human_analyst_targets_organic.length > 0)
  const hasSentiment = analysis.news_sentiment_30d != null || analysis.social_sentiment_7d != null
  const hasEvents = Boolean(analysis.events && analysis.events.length > 0)
  const hasCatalysts = Boolean(
    (analysis.short_catalysts && analysis.short_catalysts.length > 0) ||
    (analysis.long_catalysts && analysis.long_catalysts.length > 0)
  )
  const decision = useMemo(() => buildDecisionSummary(analysis), [analysis])
  const scenarioVsPrice = fmtScenarioVsPrice(analysis)
  const freshnessItems: DataFreshnessItem[] = [
    {
      label: 'AI Memo',
      asOf: analysis.as_of_date ?? null,
      version: analysis.source_name ? `Model: ${analysis.source_name}` : 'Model: internal',
      status: analysis.as_of_date ? 'ok' : 'missing',
      missingReason: analysis.as_of_date ? null : 'Memo unavailable',
    },
  ]

  const sectionNav = useMemo(() => ([
    { id: 'decision', label: 'Decision' },
    { id: 'summary', label: 'Summary' },
    { id: 'analyst', label: 'Analyst' },
    { id: 'drivers', label: 'Drivers' },
    ...(hasHumanTargets ? [{ id: 'targets', label: 'Targets' }] : []),
    { id: 'scenarios', label: 'Scenarios' },
    { id: 'sentiment', label: 'Sentiment' },
    ...(hasEvents ? [{ id: 'events', label: 'Events' }] : []),
    ...(hasCatalysts ? [{ id: 'catalysts', label: 'Catalysts' }] : []),
    { id: 'risks', label: 'Risks' },
    { id: 'peers', label: 'Peers' },
    { id: 'sources', label: 'Sources' },
  ]), [hasCatalysts, hasEvents, hasHumanTargets])

  const sectionLinks = useMemo(
    () => sectionNav.map((item) => ({ label: item.label, href: `#${item.id}` })),
    [sectionNav],
  )
  const [activeSection, setActiveSection] = useState(sectionNav[0]?.id ?? 'summary')

  useEffect(() => {
    if (typeof window === 'undefined') return
    const ids = sectionNav.map((item) => item.id)
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => Boolean(el))
    if (!elements.length) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting)
        if (!visible.length) return
        visible.sort((a, b) => b.intersectionRatio - a.intersectionRatio)
        const top = visible[0]?.target
        if (top && top.id) setActiveSection(top.id)
      },
      { rootMargin: '0px 0px -55% 0px', threshold: [0.1, 0.25, 0.5, 0.75] },
    )

    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [sectionNav])

  const normalizePeerSymbol = (raw: string) => {
    const trimmed = (raw || '').trim()
    if (!trimmed) return { display: '', href: '' }
    let display = trimmed.toUpperCase()
    if (display.includes(':')) {
      display = display.split(':').pop() || display
    }
    if (display.includes(' ')) {
      display = display.split(' ')[0] || display
    }
    const href = display ? `/ai-analysis/${encodeURIComponent(display)}` : ''
    return { display, href }
  }

  function safeHttpHref(href: unknown): string | undefined {
    if (typeof href !== 'string') return undefined
    const s = href.trim()
    if (!/^https?:\/\//i.test(s)) return undefined
    return s
  }

  return (
    <div className="space-y-6" id="top">
      <PageHeader
        title={analysis.symbol}
        subtitle={`${analysis.company_name ? `${analysis.company_name} - ` : ''}AI memo (longform). Updated bi-weekly / post-earnings.`}
        contextBadges={headerContextBadges}
        titleAddon={(
          <>
            {analysis.overall_rating ? (
              <Badge variant="model" className="px-3 py-1 text-sm">
                Rating {analysis.overall_rating}
              </Badge>
            ) : null}
            <span className="inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-2.5 py-1 text-[11px] font-semibold text-muted-foreground">
              <SparklesIcon className="h-3.5 w-3.5" aria-hidden />
              AI Memo
            </span>
          </>
        )}
        primaryAction={(
          <PrimaryCtaLink href={`/ticker/${encodeURIComponent(analysis.symbol)}`}>
            Open ticker
          </PrimaryCtaLink>
        )}
        secondaryActions={[
          <PrimaryBackLink key="ai-back" kind="ai" />,
        ]}
        tabs={(
          <nav
            aria-label="AI memo sections"
            className="sticky top-20 z-20 -mx-2 border-b border-outline/10 bg-background/85 px-2 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/70 md:top-24 lg:hidden"
          >
            <div className="flex items-center gap-3">
              <TabNav className="flex-1 overflow-x-auto whitespace-nowrap pb-1">
                {sectionNav.map((item) => (
                  <TabAnchor
                    key={item.id}
                    href={`#${item.id}`}
                    active={activeSection === item.id}
                    className="bg-secondary/10 hover:bg-secondary/16 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    {item.label}
                  </TabAnchor>
                ))}
              </TabNav>
              <a
                href="#top"
                className="text-xs font-semibold text-muted-foreground transition hover:text-foreground"
              >
                Back to top
              </a>
            </div>
          </nav>
        )}
      />
      <DataFreshnessBar items={freshnessItems} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr),240px]">
        <div className="space-y-6">
          <section id="decision" className="scroll-mt-24 md:scroll-mt-28">
            <Card className="border-outline/10">
              <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle>Decision Panel</CardTitle>
                  <CardDescription>Action, confidence, horizon, and decision blockers at a glance.</CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full px-3 text-xs"
                    onClick={() => copyDecisionSummary(decision.summaryText, toast)}
                  >
                    Copy summary
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full px-3 text-xs"
                    onClick={() => exportMemoMarkdown(analysis, decision, toast)}
                  >
                    Export memo (Markdown)
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full px-3 text-xs"
                    onClick={() => window.print()}
                  >
                    Export memo (PDF)
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
                <div className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <NoteStat label="Action" value={decision.action} strong />
                    <NoteStat label="Confidence" value={decision.confidence} />
                    <NoteStat label="Horizon" value={decision.horizon} />
                  </div>
                  <div className="rounded-xl border border-outline/10 bg-secondary/10 p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Key catalyst</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">{decision.catalystLabel}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Expected move: {decision.expectedMove}
                    </div>
                  </div>
                </div>
                <div className="space-y-3">
                  <DecisionLine label="Biggest risk" value={decision.biggestRisk} />
                  <DecisionLine label="Invalidation" value={decision.invalidation} />
                  <DecisionLine label="What would change my mind?" value={decision.changeMind} />
                </div>
              </CardContent>
            </Card>
          </section>

          <Card className="border-outline/10">
            <CardContent className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="space-y-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Research note</div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <NoteStat label="Recommendation" value={analysis.overall_rating || '—'} strong />
                  <NoteStat label="Confidence" value={analysis.confidence || '—'} />
                  <NoteStat label="As of" value={asOf || '—'} />
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <NoteStat
                  label="Base target"
                  value={fmtPriceTarget(analysis.base_price_target)}
                  helper={`p=${fmtProbability(analysis.base_probability_pct)}`}
                />
                <NoteStat
                  label="Bull target"
                  value={fmtPriceTarget(analysis.bull_price_target)}
                  helper={`p=${fmtProbability(analysis.bull_probability_pct)}`}
                />
                <NoteStat
                  label="Bear target"
                  value={fmtPriceTarget(analysis.bear_price_target)}
                  helper={`p=${fmtProbability(analysis.bear_probability_pct)}`}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Key bullets</CardTitle>
              <CardDescription>Fast scan of bull, bear, and watch items</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <KeyBulletBlock label="Bull" tone="success" items={keyBullets.bull} />
                <KeyBulletBlock label="Bear" tone="danger" items={keyBullets.bear} />
                <KeyBulletBlock label="Watch" tone="secondary" items={keyBullets.watch} />
              </div>
            </CardContent>
          </Card>

          <section id="summary" className="scroll-mt-24 md:scroll-mt-28">
            <Card>
              <CardHeader>
                <CardTitle>Summary</CardTitle>
                <CardDescription>High-level snapshot</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
                  <Field label="Recommendation" value={analysis.overall_rating} />
                  <Field label="Model confidence" value={analysis.confidence} />
                  <Field label="Timeframe" value={analysis.recommendation_timeframe} />
                  <Field label="Asset" value={analysis.asset_type} />
                </div>
                <div className="mt-4 space-y-2 text-xs text-muted-foreground">
                  <div>Base case: {fmtBaseCaseLine(analysis.base_price_target, analysis.base_probability_pct)}</div>
                  <div>
                    Bull/Bear spread:{' '}
                    {fmtBullBearSpread({
                      bullDelta: analysis.delta_bull_pct,
                      bearDelta: analysis.delta_bear_pct,
                      basePt: analysis.base_price_target,
                      bullPt: analysis.bull_price_target,
                      bearPt: analysis.bear_price_target,
                    })}
                  </div>
                  {scenarioVsPrice ? (
                    <div>Vs latest close: {scenarioVsPrice}</div>
                  ) : null}
                </div>

                <div className="mt-3 rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2 text-xs text-muted-foreground">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-foreground">Scenario probabilities</div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5">
                      Bull Target: {fmtScenarioLine(analysis.bull_price_target, analysis.bull_probability_pct)}
                    </span>
                    <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5">
                      Base Target: {fmtScenarioLine(analysis.base_price_target, analysis.base_probability_pct)}
                    </span>
                    <span className="rounded-full border border-outline/10 bg-background px-2 py-0.5">
                      Bear Target: {fmtScenarioLine(analysis.bear_price_target, analysis.bear_probability_pct)}
                    </span>
                  </div>
                </div>

                {analysis.commentary && (
                  <details className="mt-4 rounded-md border border-outline/10 bg-card p-4 text-sm text-muted-foreground">
                    <summary className="cursor-pointer text-sm font-semibold text-foreground">
                      Commentary
                    </summary>
                    <div className="mt-2 leading-relaxed text-muted-foreground">
                      {analysis.commentary}
                    </div>
                  </details>
                )}
              </CardContent>
              <DataFooter
                asOf={analysis.as_of_date ?? null}
                source="Internal model"
                cadence="Bi-weekly / post-earnings"
                links={[{ label: 'Methodology', href: '/about/ai-analysis' }]}
                className="px-4 pb-4 sm:px-6 sm:pb-6"
              />
            </Card>
          </section>

          <section id="analyst" className="scroll-mt-24 md:scroll-mt-28">
            <Card>
              <CardHeader>
                <CardTitle>Analyst Summary</CardTitle>
                <CardDescription>Thesis highlights from the latest analysis</CardDescription>
              </CardHeader>
              <CardContent>
                {analysis.analyst_summary ? (
                  <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
                    <Field label="Bull Case" value={analysis.analyst_summary.bull_case} />
                    <Field label="Bear Case" value={analysis.analyst_summary.bear_case} />
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">No analyst summary</div>
                )}
              </CardContent>
            </Card>
          </section>

      <section id="drivers" className="scroll-mt-24 md:scroll-mt-28">
        <Card>
          <CardHeader>
            <CardTitle>Drivers</CardTitle>
            <CardDescription>Scannable catalysts and supporting factors</CardDescription>
          </CardHeader>
          <CardContent>
            {drivers.length > 0 ? (
              <ul className="list-disc space-y-2 pl-5 text-sm">
                {drivers.map((driver, idx) => (
                  <li key={idx}>{driver}</li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-muted-foreground">No drivers listed</div>
            )}
          </CardContent>
        </Card>
      </section>

      {hasHumanTargets && (
        <section id="targets" className="scroll-mt-24 md:scroll-mt-28">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <CardTitle>Human Analyst Targets</CardTitle>
                  <CardDescription>External snippets for comparison only; verify at source.</CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="warning" className="text-[10px] font-semibold uppercase">
                    Unverified external
                  </Badge>
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Last fetched {asOf || '—'}
                  </span>
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Source quality: external scrape
                  </span>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="mb-3 rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2 text-xs text-muted-foreground">
                External snippets are unverified; treat as directional signals only. Always confirm with the original provider.
              </div>
              {humanTargetMeta && (
                <div className="mb-3">
                  <div className={humanTargetMeta.className}>
                    <humanTargetMeta.Icon className="h-3.5 w-3.5" aria-hidden />
                    <span>{humanTargetMeta.label}</span>
                  </div>
                </div>
              )}
              {SHOW_RAW_DATA ? (
                <>
                  <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
                    <Field label="Provider" value={analysis.human_analyst_targets_provider} />
                    <Field label="Median (USD)" value={fmtUsd(analysis.human_analyst_target_median_usd)} />
                    <Field
                      label="Range (USD)"
                      value={fmtRangeUsd(analysis.human_analyst_target_low_usd, analysis.human_analyst_target_high_usd)}
                    />
                    <Field
                      label="Count"
                      value={analysis.human_analyst_target_count != null ? String(analysis.human_analyst_target_count) : undefined}
                    />
                  </div>

                  {analysis.human_analyst_targets_query && (
                    <div className="mt-3 text-xs text-muted-foreground">
                      Query: <span className="font-mono">{analysis.human_analyst_targets_query}</span>
                    </div>
                  )}

                  {analysis.human_analyst_targets_organic && analysis.human_analyst_targets_organic.length > 0 && (
                    <ul className="mt-4 space-y-3">
                      {analysis.human_analyst_targets_organic.slice(0, 6).map((it: HumanAnalystTargetOrganicItem, idx: number) => (
                        <li key={idx} className="rounded-md border p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="font-medium">{it.title || 'Result'}</div>
                            {it.position != null && <div className="text-xs text-muted-foreground">Serper #{it.position}</div>}
                          </div>
                          {it.snippet && <div className="mt-1 text-sm text-muted-foreground">{it.snippet}</div>}
                          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                            {Array.isArray(it.amounts_usd) && it.amounts_usd.length > 0 && (
                              <span>Extracted: {it.amounts_usd.slice(0, 6).map((n) => fmtUsd(Number(n)) ?? '-').join(', ')}</span>
                            )}
                            {safeHttpHref(it.link) && (
                              <a
                                className="inline-flex h-8 items-center rounded-full border border-outline/10 bg-background px-3 text-xs font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                href={safeHttpHref(it.link)}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Open source
                              </a>
                            )}
                            {it.date && <span>{it.date}</span>}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <div className="space-y-4">
                  <div className="relative rounded-xl border border-outline/10 bg-secondary/10 p-4">
                    <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
                      <RedactedField label="Provider" value="****" />
                      <RedactedField label="Median (USD)" value="$---.--" />
                      <RedactedField label="Range (USD)" value="$---.--" />
                      <RedactedField label="Count" value="--" />
                    </div>
                    <div className="mt-3 space-y-2">
                      <div className="h-3 w-4/5 rounded bg-muted/60 blur-sm" />
                      <div className="h-3 w-3/5 rounded bg-muted/60 blur-sm" />
                    </div>
                    <RedactedOverlay />
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section id="scenarios" className="scroll-mt-24 md:scroll-mt-28">
          <Card>
            <CardHeader>
              <CardTitle>Scenarios</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Bull Target (Scenario probability)" value={fmtCase(analysis.bull_price_target, analysis.bull_probability_pct)} />
              <Field label="Base Target (Scenario probability)" value={fmtCase(analysis.base_price_target, analysis.base_probability_pct)} />
              <Field label="Bear Target (Scenario probability)" value={fmtCase(analysis.bear_price_target, analysis.bear_probability_pct)} />
            </CardContent>
            {((SHOW_RAW_DATA && analysis.price_close != null) || analysis.nearest_scenario || scenarioVsPrice) && (
              <CardContent>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {SHOW_RAW_DATA && analysis.price_close != null && (
                    <div>
                      Price ${Math.round(Number(analysis.price_close))}
                      {analysis.price_date ? ` as of ${formatEasternDate(analysis.price_date)}` : ''}
                    </div>
                  )}
                  {analysis.nearest_scenario && (
                    <div>
                      Nearest Scenario: {capitalize(analysis.nearest_scenario)} (∆ {analysis.nearest_distance_pct !== undefined ? Math.round(Number(analysis.nearest_distance_pct)) : '-'}%)
                    </div>
                  )}
                  {scenarioVsPrice ? (
                    <div>Targets vs latest close: {scenarioVsPrice}</div>
                  ) : null}
                </div>
              </CardContent>
            )}
          </Card>
        </section>

        <section id="sentiment" className="scroll-mt-24 md:scroll-mt-28">
          <Card>
            <CardHeader>
              <CardTitle>Sentiment & Exposure</CardTitle>
            </CardHeader>
            <CardContent className="text-sm">
              {hasSentiment ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="News Sentiment (30d)" value={fmt(analysis.news_sentiment_30d)} />
                  <Field label="Social Sentiment (7d)" value={fmt(analysis.social_sentiment_7d)} />
                </div>
              ) : (
                <div className="text-muted-foreground">Sentiment unavailable: insufficient coverage</div>
              )}
            </CardContent>
          </Card>
        </section>
      </div>

      {hasEvents && (
        <section id="events" className="scroll-mt-24 md:scroll-mt-28">
          <Card>
            <CardHeader>
              <CardTitle>Events</CardTitle>
              <CardDescription>Other notable items detected</CardDescription>
            </CardHeader>
            <CardContent>
              {analysis.events && analysis.events.length > 0 ? (
                <ul className="space-y-3">
                  {analysis.events.map((e: any, idx: number) => (
                    <li key={idx} className="rounded-md border p-3">
                      <div className="flex items-center justify-between">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="secondary" className="text-[10px] font-semibold">
                            {(e.catalyst_type || 'event').toString().toUpperCase()}
                          </Badge>
                          {e.expected_date && (
                            <Badge variant="outline" className="text-[10px] font-semibold">
                              {e.expected_date}
                            </Badge>
                          )}
                        </div>
                      </div>
                      {e.title && <div className="mt-1 text-sm">{e.title}</div>}
                      {e.description && <div className="mt-1 text-sm text-muted-foreground">{e.description}</div>}
                      <div className="mt-1 text-xs text-muted-foreground">
                        {e.probability_pct !== undefined && <span>Prob {fmtPct(e.probability_pct)} • </span>}
                        {e.expected_price_move_pct !== undefined && <span>Move {fmtPct(e.expected_price_move_pct)} • </span>}
                        {e.priced_in_pct !== undefined && <span>Priced-in {fmtPct(e.priced_in_pct)}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-sm text-muted-foreground">No events</div>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      {hasCatalysts && (
        <section id="catalysts" className="scroll-mt-24 md:scroll-mt-28">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Short-term Catalysts</CardTitle>
                <CardDescription>Next few weeks</CardDescription>
              </CardHeader>
              <CardContent>
                {analysis.short_catalysts && analysis.short_catalysts.length > 0 ? (
                  <ul className="space-y-3">
                    {analysis.short_catalysts.map((c: any, idx: number) => (
                      <li key={idx} className="rounded-md border p-3">
                        <div className="font-medium">{c.title}</div>
                        <div className="mb-1 text-xs text-muted-foreground">{c.expected_date || 'TBD'}</div>
                        {c.description && <div className="mb-1 text-sm">{c.description}</div>}
                        <div className="text-xs text-muted-foreground">
                          Prob {fmtPct0(c.probability_pct)} • Move {fmtPct0(c.expected_price_move_pct)} • Priced-in {fmtPct0(c.priced_in_pct)}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-sm text-muted-foreground">No short-term catalysts</div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Long-term Catalysts</CardTitle>
                <CardDescription>Months to a year</CardDescription>
              </CardHeader>
              <CardContent>
                {analysis.long_catalysts && analysis.long_catalysts.length > 0 ? (
                  <ul className="space-y-3">
                    {analysis.long_catalysts.map((c: any, idx: number) => (
                      <li key={idx} className="rounded-md border p-3">
                        <div className="font-medium">{c.title}</div>
                        <div className="mb-1 text-xs text-muted-foreground">{c.expected_date || 'TBD'}</div>
                        {c.description && <div className="mb-1 text-sm">{c.description}</div>}
                        <div className="text-xs text-muted-foreground">
                          Prob {fmtPct0(c.probability_pct)} • Move {fmtPct0(c.expected_price_move_pct)} • Priced-in {fmtPct0(c.priced_in_pct)}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-sm text-muted-foreground">No long-term catalysts</div>
                )}
              </CardContent>
            </Card>
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section id="risks" className="scroll-mt-24 md:scroll-mt-28">
          <Card>
            <CardHeader>
              <CardTitle>Risks</CardTitle>
            </CardHeader>
            <CardContent>
              {riskItems.length > 0 ? (
                <ul className="list-disc space-y-2 pl-5 text-sm">
                  {riskItems.map((risk, idx: number) => (
                    <li key={idx}>{risk}</li>
                  ))}
                </ul>
              ) : (
                <div className="text-sm text-muted-foreground">No risks</div>
              )}
            </CardContent>
          </Card>
        </section>

        <section id="peers" className="scroll-mt-24 md:scroll-mt-28">
          <Card>
            <CardHeader>
              <CardTitle>Peers</CardTitle>
            </CardHeader>
            <CardContent>
              {Array.isArray(analysis.peers) && analysis.peers.length > 0 ? (
                <div className="overflow-x-auto">
                  <DataTable>
                    <thead>
                      <tr className="text-left text-muted-foreground">
                        <th className="py-1 pr-4">
                          <ColumnHeaderTooltip label="Symbol" tooltipKey="table.symbol" />
                        </th>
                        <th className="py-1 pr-4">
                          <ColumnHeaderTooltip label="Summary" tooltipKey="ai.peers.summary" />
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.peers.map((p: any, idx: number) => {
                        const normalized = normalizePeerSymbol(p?.peer_symbol || '')
                        return (
                          <tr key={idx} className="border-t">
                            <td className="py-1 pr-4 font-medium">
                              {normalized.href ? (
                                <Link
                                  href={normalized.href}
                                  className="text-primary underline-offset-4 hover:underline"
                                >
                                  {normalized.display || '-'}
                                </Link>
                              ) : (
                                <span>{normalized.display || '-'}</span>
                              )}
                            </td>
                            <td className="py-1 pr-4">{p.summary || '-'}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </DataTable>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">No peer data</div>
              )}
            </CardContent>
          </Card>
        </section>
        <section id="sources" className="scroll-mt-24 md:scroll-mt-28">
          <Card>
            <CardHeader>
              <CardTitle>Sources</CardTitle>
              <CardDescription>Internal and external references used in this analysis</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="list-disc space-y-2 pl-5 text-sm">
                {sources.map((source, idx) => (
                  <li key={idx}>{source}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </section>
      </div>
    </div>
    <aside className="hidden lg:block">
        <div className="sticky top-24 space-y-3">
          <TickerSectionNav
            groups={[{ label: 'Sections', items: sectionLinks }]}
            activeHref={`#${activeSection}`}
            backToTop={{ href: '#top' }}
          />
        </div>
      </aside>
    </div>
  </div>
  )
}

function KeyBulletBlock({
  label,
  tone,
  items,
}: {
  label: string
  tone: BadgeProps['variant']
  items: string[]
}) {
  const list = items.length ? items : ['No highlights available yet.']
  return (
    <div className="rounded-xl border border-outline/10 bg-secondary/10 p-3 text-sm">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <Badge variant={tone} className="px-2 py-0.5 text-[10px]">
          {label}
        </Badge>
        <span>Key bullets</span>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
        {list.slice(0, 3).map((item, idx) => (
          <li key={`${label}-${idx}`}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function buildKeyBullets(analysis: AiAnalysisItem) {
  const bullInputs = [
    ...(analysis.short_catalysts ?? []).map((c: any) => c?.title || c?.description),
    ...(analysis.long_catalysts ?? []).map((c: any) => c?.title || c?.description),
    analysis.analyst_summary?.bull_case,
    analysis.analyst_summary?.valuation_check,
  ]
  const bearInputs = [
    ...(analysis.headline_risks ?? []),
    ...(analysis.macro_risks ?? []),
    ...(analysis.data_gaps ?? []),
    analysis.analyst_summary?.bear_case,
  ]
  const watchInputs = [
    ...(analysis.events ?? []).map((e: any) => e?.title || e?.description),
    analysis.analyst_summary?.valuation_check,
    analysis.commentary,
  ]

  const normalize = (items: Array<string | null | undefined>) => {
    const out: string[] = []
    items.forEach((entry) => {
      if (!entry) return
      const text = entry.toString().trim()
      if (!text) return
      splitToSentences(text).forEach((sentence) => {
        if (sentence && !out.includes(sentence)) out.push(sentence)
      })
    })
    return out
  }

  const bull = normalize(bullInputs).slice(0, 3)
  const bear = normalize(bearInputs).slice(0, 3)
  const watch = normalize(watchInputs).slice(0, 1)

  return {
    bull: bull.length ? bull : ['Catalysts and upside drivers still forming.'],
    bear: bear.length ? bear : ['No material risks flagged yet.'],
    watch: watch.length ? watch : ['Monitor upcoming catalysts and pricing vs base case.'],
  }
}

function Field({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium">{value ?? '-'}</div>
    </div>
  )
}

function RedactedField({ label, value }: { label: string; value?: string }) {
  return (
    <div className="select-none">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium blur-sm text-muted-foreground/70">{value ?? '—'}</div>
    </div>
  )
}

function NoteStat({
  label,
  value,
  helper,
  strong,
}: {
  label: string
  value: string
  helper?: string
  strong?: boolean
}) {
  return (
    <div className="rounded-lg border border-outline/10 bg-card p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={strong ? 'mt-1 text-lg font-semibold text-foreground' : 'mt-1 text-base font-semibold text-foreground'}>
        {value}
      </div>
      {helper ? <div className="mt-0.5 text-xs text-muted-foreground">{helper}</div> : null}
    </div>
  )
}

function DecisionLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-outline/10 bg-secondary/10 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold text-foreground">{value}</div>
    </div>
  )
}

function fmt(n?: number): string | undefined {
  if (n === null || n === undefined) return undefined
  const v = Number(n)
  if (Number.isNaN(v)) return undefined
  return v.toFixed(2)
}

function fmtPct(n?: number): string | undefined {
  if (n === null || n === undefined) return undefined
  return `${Number(n).toFixed(2)}%`
}

function fmtPct0(n?: number): string | undefined {
  if (n === null || n === undefined) return undefined
  const v = Number(n)
  if (Number.isNaN(v)) return undefined
  return `${Math.round(v)}%`
}

function fmtCase(pt?: number, prob?: number): string | undefined {
  let price: string | undefined
  if (pt !== null && pt !== undefined && !Number.isNaN(Number(pt))) {
    price = `$${Math.round(Number(pt))}`
  }
  let p: string | undefined
  if (prob !== null && prob !== undefined && !Number.isNaN(Number(prob))) {
    p = `p=${Math.round(Number(prob))}%`
  }
  if (price && p) return `${price} / ${p} prob`
  if (price) return price
  if (p) return `${p} prob`
  return undefined
}

function fmtBaseCaseLine(pt?: number, prob?: number) {
  return `${fmtPriceTarget(pt)} (p=${fmtProbability(prob)})`
}

function fmtScenarioLine(pt?: number, prob?: number) {
  return `${fmtPriceTarget(pt)} (p=${fmtProbability(prob)})`
}

function fmtScenarioVsPrice(analysis: AiAnalysisItem) {
  const base = analysis.price_close
  const bull = analysis.delta_bull_pct ?? computePct(analysis.bull_price_target, base)
  const baseDelta = analysis.delta_base_pct ?? computePct(analysis.base_price_target, base)
  const bear = analysis.delta_bear_pct ?? computePct(analysis.bear_price_target, base)
  const hasAny =
    (bull != null && !Number.isNaN(Number(bull))) ||
    (baseDelta != null && !Number.isNaN(Number(baseDelta))) ||
    (bear != null && !Number.isNaN(Number(bear)))
  if (!hasAny) return null
  return `Bull ${fmtPctSigned(bull)} · Base ${fmtPctSigned(baseDelta)} · Bear ${fmtPctSigned(bear)}`
}

type DecisionSummary = {
  action: string
  confidence: string
  horizon: string
  catalystLabel: string
  expectedMove: string
  biggestRisk: string
  invalidation: string
  changeMind: string
  summaryText: string
}

function formatMaybeDate(value?: string) {
  if (!value) return ''
  return formatEasternDate(value)
}

function pickNextEvent(events?: any[]) {
  const list = (events || [])
    .map((e) => ({
      title: (e?.title || e?.description || '').toString().trim(),
      expected_date: e?.expected_date ? String(e.expected_date).trim() : '',
    }))
    .filter((e) => e.title || e.expected_date)
  if (!list.length) return null
  const dated = list.filter((e) => /^\d{4}-\d{2}-\d{2}/.test(e.expected_date))
  if (dated.length) {
    const ordered = dated.slice().sort((a, b) => a.expected_date.localeCompare(b.expected_date))
    return ordered[0] ?? null
  }
  return list[0] ?? null
}

function pickCatalyst(analysis: AiAnalysisItem) {
  const nextEvent = pickNextEvent(analysis.events)
  if (nextEvent) return { label: nextEvent.title || 'Upcoming event', date: nextEvent.expected_date }
  const catalyst =
    (analysis.short_catalysts || []).find((c: any) => c?.title || c?.description) ||
    (analysis.long_catalysts || []).find((c: any) => c?.title || c?.description)
  if (catalyst) {
    return { label: (catalyst.title || catalyst.description || '').toString().trim(), date: catalyst.expected_date || '' }
  }
  return null
}

function buildDecisionSummary(analysis: AiAnalysisItem): DecisionSummary {
  const riskItems = [
    ...(analysis.headline_risks ?? []),
    ...(analysis.macro_risks ?? []),
    ...(analysis.data_gaps ?? []),
  ].filter(Boolean)
  const biggestRisk = analysis.analyst_summary?.bear_case || riskItems[0] || 'No material risks flagged yet.'
  const bullCase = analysis.analyst_summary?.bull_case
  const catalyst = pickCatalyst(analysis)
  const catalystLabel = catalyst
    ? `${catalyst.label}${catalyst.date ? ` • ${formatMaybeDate(catalyst.date)}` : ''}`
    : 'No scheduled catalysts flagged.'
  const expectedMoveRaw =
    analysis.delta_base_pct ?? computePct(analysis.base_price_target, analysis.price_close)
  const expectedMove = fmtPctSigned(expectedMoveRaw)
  const invalidation = analysis.bear_price_target
    ? `Break below ${fmtPriceTarget(analysis.bear_price_target)} or thesis failure.`
    : analysis.analyst_summary?.bear_case || 'Failure of key catalysts or margin pressure.'
  const changeMind = bullCase || catalyst?.label || 'Material positive surprise or improving fundamentals.'
  const action = analysis.overall_rating || '—'
  const confidence = analysis.confidence || '—'
  const horizon = analysis.recommendation_timeframe || '—'
  const summaryText = [
    `Action: ${action}`,
    `Confidence: ${confidence}`,
    `Horizon: ${horizon}`,
    `Key catalyst: ${catalystLabel}`,
    `Expected move (to base): ${expectedMove}`,
    `Biggest risk: ${biggestRisk}`,
    `Invalidation: ${invalidation}`,
    `What would change my mind: ${changeMind}`,
  ].join('\n')

  return {
    action,
    confidence,
    horizon,
    catalystLabel,
    expectedMove,
    biggestRisk,
    invalidation,
    changeMind,
    summaryText,
  }
}

function copyDecisionSummary(summaryText: string, toast: ReturnType<typeof useToast>['toast']) {
  try {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(summaryText).then(
        () => toast({ title: 'Summary copied', description: 'Decision panel copied to clipboard.' }),
        () => toast({ title: 'Copy failed', description: 'Clipboard access was blocked.' }),
      )
      return
    }
  } catch {
    // fall through to fallback
  }
  try {
    const area = document.createElement('textarea')
    area.value = summaryText
    area.setAttribute('readonly', 'true')
    area.style.position = 'fixed'
    area.style.left = '-9999px'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    area.remove()
    toast(ok
      ? { title: 'Summary copied', description: 'Decision panel copied to clipboard.' }
      : { title: 'Copy failed', description: 'Clipboard access was blocked.' }
    )
  } catch {
    toast({ title: 'Copy failed', description: 'Clipboard access was blocked.' })
  }
}

function exportMemoMarkdown(analysis: AiAnalysisItem, decision: DecisionSummary, toast: ReturnType<typeof useToast>['toast']) {
  const markdown = buildMemoMarkdown(analysis, decision)
  const filename = `${analysis.symbol}-ai-memo.md`.toLowerCase()
  downloadTextFile(filename, markdown)
  toast({ title: 'Exported memo', description: `Saved ${filename}` })
}

function buildMemoMarkdown(analysis: AiAnalysisItem, decision: DecisionSummary) {
  const keyBullets = buildKeyBullets(analysis)
  const sources = buildSources(analysis)
  const asOf = analysis.as_of_date ? formatEasternDate(analysis.as_of_date) : '—'
  const scenarios = [
    `Bull: ${fmtScenarioLine(analysis.bull_price_target, analysis.bull_probability_pct)}`,
    `Base: ${fmtScenarioLine(analysis.base_price_target, analysis.base_probability_pct)}`,
    `Bear: ${fmtScenarioLine(analysis.bear_price_target, analysis.bear_probability_pct)}`,
  ].join('\n')
  const risks = [
    ...(analysis.headline_risks ?? []),
    ...(analysis.macro_risks ?? []),
    ...(analysis.data_gaps ?? []),
  ].filter(Boolean)
  const catalysts = [
    ...(analysis.short_catalysts ?? []),
    ...(analysis.long_catalysts ?? []),
  ].map((c: any) => c?.title || c?.description).filter(Boolean)

  return [
    `# AI Memo: ${analysis.symbol}`,
    '',
    `As of: ${asOf}`,
    '',
    '## Decision Panel',
    decision.summaryText,
    '',
    '## Key Bullets',
    `Bull: ${keyBullets.bull.join('; ') || '—'}`,
    `Bear: ${keyBullets.bear.join('; ') || '—'}`,
    `Watch: ${keyBullets.watch.join('; ') || '—'}`,
    '',
    '## Scenarios',
    scenarios,
    '',
    '## Catalysts',
    catalysts.length ? catalysts.map((c) => `- ${c}`).join('\n') : '- No catalysts listed.',
    '',
    '## Risks',
    risks.length ? risks.map((r) => `- ${r}`).join('\n') : '- No risks listed.',
    '',
    '## Sources',
    sources.length ? sources.map((s) => `- ${s}`).join('\n') : '- No sources listed.',
    '',
  ].join('\n')
}

function downloadTextFile(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function extractDrivers(analysis: AiAnalysisItem): string[] {
  const catalysts = [
    ...(analysis.short_catalysts ?? []),
    ...(analysis.long_catalysts ?? []),
  ]
    .map((c: any) => (c?.title || c?.description || '').toString().trim())
    .filter(Boolean)

  if (catalysts.length) return catalysts.slice(0, 6)

  const summarySeed =
    analysis.analyst_summary?.bull_case ||
    analysis.analyst_summary?.valuation_check ||
    analysis.commentary ||
    ''
  const sentences = splitToSentences(summarySeed)
  return sentences.slice(0, 4)
}

function splitToSentences(text: string): string[] {
  const cleaned = text.replace(/\s+/g, ' ').trim()
  if (!cleaned) return []
  const parts = cleaned.split(/(?<=[.!?])\s+/)
  return parts.map((p) => p.trim()).filter(Boolean)
}

function buildSources(analysis: AiAnalysisItem): string[] {
  const sources: string[] = []
  if (analysis.source_name) {
    sources.push(`Model source: ${analysis.source_name}`)
  } else {
    sources.push('Model source: internal (not provided)')
  }
  if (analysis.human_analyst_targets_provider) {
    sources.push(`Human targets: ${analysis.human_analyst_targets_provider}`)
  }
  if (analysis.human_analyst_targets_query) {
    sources.push(`Targets query: ${analysis.human_analyst_targets_query}`)
  }
  if (analysis.as_of_date) {
    sources.push(`Analysis date: ${formatEasternDate(analysis.as_of_date)}`)
  }
  return sources
}

function capitalize(s?: string): string {
  if (!s) return ''
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function fmtUsd(n?: number): string | undefined {
  if (n === null || n === undefined) return undefined
  const v = Number(n)
  if (Number.isNaN(v)) return undefined
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(v)
}

function fmtRangeUsd(low?: number, high?: number): string | undefined {
  const lo = fmtUsd(low)
  const hi = fmtUsd(high)
  if (!lo && !hi) return undefined
  if (lo && hi) return `${lo} - ${hi}`
  return lo ?? hi
}
