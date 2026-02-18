import { RankingsView } from '@/features/explore/rankings-view'
import type { Metadata } from 'next'
import { Suspense } from 'react'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { buildUpstreamUrl } from '@/app/api/_utils/upstream'

export function generateMetadata(): Metadata {
  const siteUrl = getCanonicalSiteUrl()
  const canonicalUrl = `${siteUrl}/rankings`
  const title = 'Rankings - Stock Grades & Factor Scores'
  const description =
    'Explore factor grades, setup hits, and momentum/value rankings across tracked stocks.'

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
      'stock rankings',
      'factor grades',
      'momentum',
      'value',
      'swing trading',
      'stock screener',
      'RankAlpha',
    ],
  }
}

type RankingItem = {
  symbol: string
  company_name?: string
  overall_grade?: string
}

async function fetchTopRankings(): Promise<RankingItem[]> {
  const qs = new URLSearchParams({
    limit: '10',
    skip: '0',
    sort_by: 'grade',
    sort_order: 'desc',
  })
  const target = buildUpstreamUrl('/api/v1/grading/grades', qs)
  try {
    const res = await fetch(target, {
      next: { revalidate: 300, tags: ['rankings', 'grades', 'grades-top'] },
    })
    if (!res.ok) return []
    const data = (await res.json()) as { stocks?: RankingItem[] }
    return Array.isArray(data?.stocks) ? data.stocks.slice(0, 10) : []
  } catch {
    return []
  }
}

export default async function RankingsPage() {
  const siteUrl = getCanonicalSiteUrl()
  const topRankings = await fetchTopRankings()
  const ldJson = JSON.stringify(
    {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: 'Rankings',
      url: `${siteUrl}/rankings`,
      description:
        'Explore factor grades, setup hits, and momentum/value rankings across tracked stocks.',
      isPartOf: {
        '@type': 'WebSite',
        name: 'RankAlpha',
        url: siteUrl,
      },
    },
    null,
    0,
  ).replace(/</g, '\\u003c')

  const itemListJson = topRankings.length
    ? JSON.stringify(
        {
          '@context': 'https://schema.org',
          '@type': 'ItemList',
          name: 'Top ranked stocks',
          itemListOrder: 'https://schema.org/ItemListOrderDescending',
          itemListElement: topRankings
            .filter((item) => item?.symbol)
            .map((item, index) => ({
              '@type': 'ListItem',
              position: index + 1,
              item: {
                '@type': 'Corporation',
                name: item.company_name || item.symbol,
                tickerSymbol: item.symbol,
                url: `${siteUrl}/ticker/${encodeURIComponent(item.symbol)}`,
                description: item.overall_grade ? `Grade ${item.overall_grade}` : undefined,
              },
            })),
        },
        null,
        0,
      ).replace(/</g, '\\u003c')
    : null

  return (
    <div className="space-y-4 sm:space-y-6">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: ldJson }} />
      {itemListJson ? (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: itemListJson }} />
      ) : null}

      <Suspense fallback={null}>
        <RankingsView />
      </Suspense>
    </div>
  )
}
