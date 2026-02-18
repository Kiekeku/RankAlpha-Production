import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { PageHero } from '@/components/page-hero'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { ScreenerConsensusView } from '@/features/explore/screener-consensus-view'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { buildUpstreamUrl } from '@/app/api/_utils/upstream'
import { slugify } from '@/lib/slug'
import { buildScreenerLeadersItemListJson } from '@/lib/screener_schema'

type StyleOption = { name: string; count: number }
type ScreenerConsensusItem = { symbol: string; company_name?: string; consensus_score?: number }

function titleFromSlug(slug: string): string {
  return slug
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

async function fetchStyleOptions(): Promise<StyleOption[] | null> {
  const target = buildUpstreamUrl('/api/v1/screener/styles/meta')
  try {
    const res = await fetch(target, {
      next: { revalidate: 3600, tags: ['screener', 'screener-styles', 'screener-styles-meta'] },
    })
    if (!res.ok) return null
    const data = (await res.json()) as StyleOption[]
    return Array.isArray(data) ? data : null
  } catch {
    return null
  }
}

async function fetchTopForStyle(styleName: string): Promise<ScreenerConsensusItem[]> {
  const qs = new URLSearchParams({
    limit: '10',
    skip: '0',
    sort_by: 'consensus_score',
    sort_order: 'desc',
  })
  qs.append('styles', styleName)
  const target = buildUpstreamUrl('/api/v1/screener/consensus', qs)
  try {
    const res = await fetch(target, {
      next: { revalidate: 300, tags: ['screener', 'screener-consensus', `screener-style:${styleName}`] },
    })
    if (!res.ok) return []
    const data = (await res.json()) as { items?: ScreenerConsensusItem[] }
    return Array.isArray(data?.items) ? data.items.slice(0, 10) : []
  } catch {
    return []
  }
}

async function resolveStyleName(slug: string): Promise<{ name: string; exists: boolean }> {
  const options = await fetchStyleOptions()
  if (options && options.length) {
    const match = options.find((opt) => slugify(opt.name) === slug)
    if (!match) return { name: titleFromSlug(slug), exists: false }
    return { name: match.name, exists: true }
  }
  return { name: titleFromSlug(slug), exists: true }
}

export async function generateMetadata(
  { params }: { params: { style: string } }
): Promise<Metadata> {
  const slug = slugify(params.style || '')
  if (!slug) {
    return { title: 'Screener' }
  }
  const siteUrl = getCanonicalSiteUrl()
  const canonicalUrl = `${siteUrl}/screener/${encodeURIComponent(slug)}`
  const resolved = await resolveStyleName(slug)
  const styleName = resolved.name
  const title = `${styleName} Screeners - Consensus Setup hits`
  const description =
    `Top ${styleName} screeners with ranked symbols, breadth, and consensus signals for swing trading.`

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
      `${styleName} screener`,
      `${styleName} stocks`,
      'stock screeners',
      'swing trading',
      'RankAlpha',
    ],
  }
}

export default async function ScreenerStylePage({ params }: { params: { style: string } }) {
  const slug = slugify(params.style || '')
  if (!slug) notFound()

  const resolved = await resolveStyleName(slug)
  if (!resolved.exists) notFound()
  const styleName = resolved.name

  const siteUrl = getCanonicalSiteUrl()
  const canonicalUrl = `${siteUrl}/screener/${encodeURIComponent(slug)}`
  const topItems = await fetchTopForStyle(styleName)

  const ldJson = JSON.stringify(
    {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: `${styleName} Screeners`,
      url: canonicalUrl,
      description:
        `Top ${styleName} screeners with ranked symbols, breadth, and consensus signals for swing trading.`,
      isPartOf: {
        '@type': 'WebSite',
        name: 'RankAlpha',
        url: siteUrl,
      },
      about: {
        '@type': 'DefinedTerm',
        name: styleName,
        inDefinedTermSet: `${siteUrl}/screener`,
      },
    },
    null,
    0,
  ).replace(/</g, '\\u003c')

  const itemListJson = buildScreenerLeadersItemListJson({
    name: `${styleName} screener leaders`,
    siteUrl,
    items: topItems,
  })

  return (
    <div className="space-y-4 sm:space-y-6">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: ldJson }} />
      {itemListJson ? (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: itemListJson }} />
      ) : null}
      <PageHero
        title={`${styleName} Screeners`}
        subtitle="Consensus screens and style-based setup hits"
        right={<PrimaryCtaLink href="/screener">All Screeners</PrimaryCtaLink>}
      />
      <ScreenerConsensusView initialStyles={[styleName]} />
    </div>
  )
}
