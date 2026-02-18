import type { Metadata } from 'next'
import { Suspense } from 'react'
import { buildUpstreamUrl } from '@/app/api/_utils/upstream'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { ScreenerPageClient } from '@/features/screener/screener-page-client'
import { slugify } from '@/lib/slug'
import { buildScreenerLeadersItemListJson } from '@/lib/screener_schema'

type ScreenerConsensusItem = {
  symbol: string
  company_name?: string
  consensus_score?: number
}

type StyleOption = { name: string; count: number }

function normalizeSymbolParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) {
    value = value[0]
  }
  return (value || '').trim().toUpperCase()
}

export function generateMetadata(
  { searchParams }: { searchParams?: { [key: string]: string | string[] | undefined } }
): Metadata {
  const siteUrl = getCanonicalSiteUrl()
  const symbol = normalizeSymbolParam(searchParams?.symbol)
  const canonicalUrl = symbol
    ? `${siteUrl}/screener?symbol=${encodeURIComponent(symbol)}`
    : `${siteUrl}/screener`

  if (symbol) {
    const title = `Screener: ${symbol} - Consensus & Setup hits`
    const description =
      `Pre-built screener results and style-based setup hits for ${symbol}.`
    return {
      title,
      description,
      alternates: { canonical: canonicalUrl },
      openGraph: {
        type: 'website',
        url: canonicalUrl,
        title,
        description,
        siteName: 'RankAlpha',
      },
      twitter: {
        card: 'summary',
        title,
        description,
      },
      keywords: [
        symbol,
        'stock screener',
        'consensus setup hits',
        'swing trading',
        'RankAlpha',
      ],
    }
  }

  const title = 'Screener -  Setup hits & Styles'
  const description =
    'Pre-built screeners and style-based setup hits for swing trading, including breadth, sources, and ranked symbols.'

  return {
    title,
    description,
    alternates: { canonical: canonicalUrl },
    openGraph: {
      type: 'website',
      url: canonicalUrl,
      title,
      description,
      siteName: 'RankAlpha',
    },
    twitter: {
      card: 'summary',
      title,
      description,
    },
    keywords: [
      'stock screeners',
      'screener consensus',
      'swing trading setup hits',
      'momentum',
      'pullback',
      'mean reversion',
      'RankAlpha',
    ],
  }
}

async function fetchTopConsensus(): Promise<ScreenerConsensusItem[]> {
  const qs = new URLSearchParams({
    limit: '10',
    skip: '0',
    sort_by: 'consensus_score',
    sort_order: 'desc',
  })
  const target = buildUpstreamUrl('/api/v1/screener/consensus', qs)
  try {
    const res = await fetch(target, {
      next: { revalidate: 300, tags: ['screener', 'screener-consensus', 'screeners-top'] },
    })
    if (!res.ok) return []
    const data = (await res.json()) as { items?: ScreenerConsensusItem[] }
    return Array.isArray(data?.items) ? data.items.slice(0, 10) : []
  } catch {
    return []
  }
}

async function fetchStyleOptions(): Promise<StyleOption[]> {
  const target = buildUpstreamUrl('/api/v1/screener/styles/meta')
  try {
    const res = await fetch(target, {
      next: { revalidate: 3600, tags: ['screener', 'screener-styles', 'screener-styles-meta'] },
    })
    if (!res.ok) return []
    const data = (await res.json()) as StyleOption[]
    return Array.isArray(data) ? data : []
  } catch {
    return []
  }
}

export default async function ScreenerPage() {
  const siteUrl = getCanonicalSiteUrl()
  const topItems = await fetchTopConsensus()
  const styleOptions = await fetchStyleOptions()
  const ldJson = JSON.stringify(
    {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: 'Screener',
      url: `${siteUrl}/screener`,
      description:
        'Pre-built screeners and style-based setup hits for swing trading, including breadth, sources, and ranked symbols.',
      isPartOf: {
        '@type': 'WebSite',
        name: 'RankAlpha',
        url: siteUrl,
      },
    },
    null,
    0,
  ).replace(/</g, '\\u003c')

  const stylesItemListJson = styleOptions.length
    ? JSON.stringify(
        {
          '@context': 'https://schema.org',
          '@type': 'ItemList',
          name: 'Screener styles',
          itemListOrder: 'https://schema.org/ItemListOrderAscending',
          itemListElement: styleOptions
            .map((style) => ({ style, slug: slugify(style?.name || '') }))
            .filter(({ style, slug }) => style?.name && slug)
            .map(({ style, slug }, index) => ({
              '@type': 'ListItem',
              position: index + 1,
              item: {
                '@type': 'CollectionPage',
                name: `${style.name} Screeners`,
                url: `${siteUrl}/screener/${encodeURIComponent(slug)}`,
              },
            })),
        },
        null,
        0,
      ).replace(/</g, '\\u003c')
    : null

  const itemListJson = buildScreenerLeadersItemListJson({
    name: 'Top screener consensus symbols',
    siteUrl,
    items: topItems,
  })

  return (
    <div className="space-y-6">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: ldJson }} />
      {stylesItemListJson ? (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: stylesItemListJson }} />
      ) : null}
      {itemListJson ? (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: itemListJson }} />
      ) : null}
      <Suspense fallback={null}>
        <ScreenerPageClient />
      </Suspense>
    </div>
  )
}
