import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound, permanentRedirect } from 'next/navigation'
import { buildUpstreamUrl } from '@/app/api/_utils/upstream'
import { AiAnalysisList, AiAnalysisItem } from '@/lib/api'
import { AiAnalysisDetailView } from '@/components/ai-analysis-detail-view'
import { PageHeader } from '@/components/page-header'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { Card, CardContent } from '@/components/ui/card'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { RecentTickerTracker } from '@/components/recent-ticker-tracker'

export const revalidate = 7200

const PLAYWRIGHT_MOCKS = process.env.PLAYWRIGHT_MOCKS === '1'

function buildMockAnalysis(symbol: string): AiAnalysisItem {
  const today = new Date().toISOString().slice(0, 10)
  return {
    analysis_id: `mock-${symbol}`,
    as_of_date: today,
    symbol,
    company_name: 'Mock Industries',
    asset_type: 'Equity',
    overall_rating: 'B+',
    confidence: 'Medium',
    recommendation_timeframe: '3-6 months',
    base_price_target: 120,
    base_probability_pct: 55,
    bull_price_target: 150,
    bull_probability_pct: 25,
    bear_price_target: 90,
    bear_probability_pct: 20,
    delta_bull_pct: 18,
    delta_bear_pct: -12,
    commentary: 'Mock analysis for UI validation.',
    analyst_summary: {
      bull_case: 'Demand growth supports upside.',
      bear_case: 'Margins compress if pricing weakens.',
      valuation_check: 'Reasonable vs sector median.',
    },
    short_catalysts: [
      { title: 'Product launch', expected_date: '2024-02-01', description: 'Launch cycle begins.' },
    ],
    long_catalysts: [
      { title: 'Margin expansion', expected_date: '2024-06-01', description: 'Scale efficiencies.' },
    ],
    events: [
      { catalyst_type: 'earnings', expected_date: '2024-02-10', title: 'Q4 earnings', description: 'Guidance update.' },
    ],
    macro_risks: ['Rates stay higher for longer.'],
    headline_risks: ['Competitive pricing pressure.'],
    data_gaps: ['Limited analyst coverage.'],
    peers: [
      { peer_symbol: 'PEER1', summary: 'Similar growth profile.' },
      { peer_symbol: 'PEER2', summary: 'Higher margins, slower growth.' },
    ],
    news_sentiment_30d: 0.18,
    social_sentiment_7d: 0.12,
    human_analyst_targets_provider: 'Mock Research',
    human_analyst_targets_query: 'Mock target price',
    human_analyst_target_low_usd: 95,
    human_analyst_target_high_usd: 145,
    human_analyst_target_median_usd: 120,
    human_analyst_target_count: 14,
    human_analyst_targets_organic: [
      {
        position: 1,
        title: 'Analyst note',
        snippet: 'Price target reiterated.',
        link: 'https://example.com/mock',
        date: '2024-01-01',
        amounts_usd: [120, 135],
      },
    ],
    human_target_vs_ra: 'inline',
  }
}

async function fetchLatestBySymbol(symbol: string): Promise<AiAnalysisItem | null> {
  const qs = new URLSearchParams({
    symbol,
    skip: '0',
    limit: '1',
    sort_by: 'date',
    sort_order: 'desc',
    include_proximity: 'true',
  })
  const target = buildUpstreamUrl('/api/v1/ai-analysis/latest', qs)
  const res = await fetch(target, {
    next: { revalidate, tags: ['ai-analysis', 'ai-analysis-latest', `ai-analysis-symbol:${symbol}`] },
  })

  if (!res.ok) return null
  const data = (await res.json()) as AiAnalysisList
  return data?.items?.[0] ?? null
}

async function fetchById(analysisId: string): Promise<AiAnalysisItem | null> {
  const trimmed = (analysisId || '').trim()
  if (!trimmed) return null
  const target = buildUpstreamUrl(`/api/v1/ai-analysis/id/${encodeURIComponent(trimmed)}`)
  const res = await fetch(target, {
    next: { revalidate, tags: ['ai-analysis', trimmed] },
  })
  if (!res.ok) return null
  return (await res.json()) as AiAnalysisItem
}

export async function generateMetadata(
  { params, searchParams }: { params: { symbol: string }; searchParams?: { analysis_id?: string } }
): Promise<Metadata> {
  const symbol = (params.symbol || '').trim().toUpperCase()
  const analysisId = (searchParams?.analysis_id || '').trim()
  if (PLAYWRIGHT_MOCKS && analysisId === 'mock') {
    const analysis = buildMockAnalysis(symbol || 'MOCK')
    const siteUrl = getCanonicalSiteUrl()
    const canonicalPath = `/ai-analysis/${encodeURIComponent(analysis.symbol)}`
    const canonicalUrl = `${siteUrl}${canonicalPath}`
    return {
      title: `AI Memo: ${analysis.symbol}${analysis.company_name ? ` - ${analysis.company_name}` : ''}`,
      description: `Mock AI memo for ${analysis.symbol}.`,
      alternates: { canonical: canonicalUrl },
      robots: { index: false, follow: true },
    }
  }
  const siteUrl = getCanonicalSiteUrl()
  const canonicalPath = `/ai-analysis/${encodeURIComponent(symbol)}`
  const canonicalUrl = `${siteUrl}${canonicalPath}`
  const analysis = analysisId ? await fetchById(analysisId) : (symbol ? await fetchLatestBySymbol(symbol) : null)

  if (!analysis) {
    return {
      title: `AI Memo: ${symbol}`,
      description: symbol ? `No AI memo yet for ${symbol}.` : 'AI memo by symbol.',
      alternates: { canonical: canonicalUrl },
      robots: { index: false, follow: true },
      openGraph: {
        type: 'website',
        url: canonicalUrl,
        title: `AI Memo: ${symbol}`,
        description: symbol ? `No AI memo yet for ${symbol}.` : 'AI memo by symbol.',
        siteName: 'RankAlpha',
      },
      twitter: {
        card: 'summary',
        title: `AI Memo: ${symbol}`,
        description: symbol ? `No AI memo yet for ${symbol}.` : 'AI memo by symbol.',
      },
    }
  }

  const descParts = [
    analysis.company_name ? `${analysis.company_name} (${analysis.symbol})` : analysis.symbol,
    analysis.overall_rating ? `Rating: ${analysis.overall_rating}` : null,
    analysis.confidence ? `Model confidence: ${analysis.confidence}` : null,
    analysis.as_of_date ? `As of ${analysis.as_of_date}` : null,
  ].filter(Boolean)

  const title = `AI Memo: ${analysis.symbol}${analysis.company_name ? ` - ${analysis.company_name}` : ''}`
  const description = descParts.join(' • ')

  return {
    title,
    description,
    alternates: { canonical: canonicalUrl },
    robots: { index: true, follow: true },
    openGraph: {
      title,
      description,
      url: canonicalUrl,
      type: 'article',
      siteName: 'RankAlpha',
    },
    twitter: {
      card: 'summary',
      title,
      description,
    },
    keywords: [
      analysis.symbol,
      ...(analysis.company_name ? [analysis.company_name] : []),
      'AI stock analysis',
      'stock outlook',
      'price targets',
      'bull base bear',
      'RankAlpha',
    ],
  }
}

export default async function AiLatestBySymbolPage({
  params,
  searchParams,
}: {
  params: { symbol: string }
  searchParams?: { analysis_id?: string }
}) {
  const raw = (params.symbol || '').trim()
  const symbol = raw.toUpperCase()
  const analysisId = (searchParams?.analysis_id || '').trim()

  if (!symbol) {
    permanentRedirect('/ai-analysis')
  }
  if (raw !== symbol) {
    permanentRedirect(`/ai-analysis/${encodeURIComponent(symbol)}${analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : ''}`)
  }

  if (PLAYWRIGHT_MOCKS && analysisId === 'mock') {
    const analysis = buildMockAnalysis(symbol)
    return (
      <>
        <RecentTickerTracker symbol={analysis.symbol} companyName={analysis.company_name} />
        <AiAnalysisDetailView analysis={analysis} />
      </>
    )
  }

  const analysis = analysisId ? await fetchById(analysisId) : await fetchLatestBySymbol(symbol)
  if (analysisId && !analysis) {
    notFound()
  }
  if (!analysis) {
    return (
      <div className="space-y-4 sm:space-y-6">
        <RecentTickerTracker symbol={symbol} />
        <PageHeader
        title={`AI Memo: ${symbol}`}
        subtitle="No memo yet. Updated bi-weekly / post-earnings."
        contextBadges={['Status: unavailable']}
        primaryAction={<PrimaryCtaLink href="/ai-analysis">Back to AI Feed</PrimaryCtaLink>}
        secondaryActions={[
          <Link
            key="open-ticker"
            href={`/ticker/${encodeURIComponent(symbol)}`}
            className="inline-flex items-center justify-center rounded-full border border-outline/20 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:border-outline/30 hover:text-foreground"
          >
            Open ticker
          </Link>,
        ]}
        />
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-2 text-sm text-muted-foreground">
              <div className="font-semibold text-foreground">No AI memo yet for {symbol}.</div>
              <div>
                Coverage is prioritized for symbols with active screener hits, A/B grades, or meaningful news/earnings.
              </div>
              <div className="space-y-1 text-xs">
                <div>Use Momentum/Value scores and setup hits to frame signal strength.</div>
                <div>Check Fundamentals for analyst targets when available.</div>
                <div>Use Sentiment proxy in the AI snapshot if present.</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (analysis.symbol && analysis.symbol.toUpperCase() !== symbol) {
    permanentRedirect(`/ai-analysis/${encodeURIComponent(analysis.symbol)}?analysis_id=${encodeURIComponent(analysisId)}`)
  }

  const siteUrl = getCanonicalSiteUrl()
  const canonicalUrl = `${siteUrl}/ai-analysis/${encodeURIComponent(analysis.symbol)}`
  const ldJson = (() => {
    const payload = {
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: `AI Memo: ${analysis.symbol}${analysis.company_name ? ` - ${analysis.company_name}` : ''}`,
      datePublished: analysis.as_of_date || undefined,
      dateModified: analysis.as_of_date || undefined,
      mainEntityOfPage: canonicalUrl,
      author: { '@type': 'Organization', name: 'RankAlpha' },
      publisher: { '@type': 'Organization', name: 'RankAlpha' },
      about: {
        '@type': 'Corporation',
        name: analysis.company_name || analysis.symbol,
        tickerSymbol: analysis.symbol,
      },
      description: [
        analysis.company_name ? `${analysis.company_name} (${analysis.symbol})` : analysis.symbol,
        analysis.overall_rating ? `Rating: ${analysis.overall_rating}` : null,
        analysis.confidence ? `Model confidence: ${analysis.confidence}` : null,
      ].filter(Boolean).join(' • '),
    }
    return JSON.stringify(payload).replace(/</g, '\\u003c')
  })()

  return (
    <>
      <RecentTickerTracker symbol={analysis.symbol} companyName={analysis.company_name} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: ldJson }} />
      <AiAnalysisDetailView analysis={analysis} />
    </>
  )
}
