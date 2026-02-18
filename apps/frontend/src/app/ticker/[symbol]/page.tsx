import type { Metadata } from 'next'
import { buildUpstreamUrl } from '@/app/api/_utils/upstream'
import type { AssetDetail } from '@/lib/api'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { StockDetailView } from '@/features/stock-detail/stock_detail_view'
import { PrimaryBackLink } from '@/components/primary-back-link'
import { TickerTabMemory } from '@/components/ticker/ticker-tab-memory'

export async function generateMetadata({ params }: { params: { symbol: string } }): Promise<Metadata> {
  const symbol = (params.symbol || '').trim().toUpperCase()
  const siteUrl = getCanonicalSiteUrl()
  const canonicalPath = symbol ? `/ticker/${encodeURIComponent(symbol)}` : '/ticker'
  const canonicalUrl = `${siteUrl}${canonicalPath}`

  let asset: AssetDetail | null = null
  if (symbol) {
    try {
      const res = await fetch(buildUpstreamUrl(`/api/v1/grading/asset/${encodeURIComponent(symbol)}`), {
        next: { revalidate: 300, tags: ['asset', `asset:${symbol}`] },
      })
      if (res.ok) asset = (await res.json()) as AssetDetail
    } catch {
      asset = null
    }
  }

  const companyName = asset?.company_name?.trim() || ''
  const grade = asset?.current_grade?.overall_grade?.trim() || ''
  const asOf = asset?.current_grade?.date?.trim() || ''

  const titleParts = [
    symbol || 'Ticker',
    companyName || undefined,
    grade ? `Grade ${grade}` : undefined,
  ].filter(Boolean)
  const title = titleParts.join(' - ')

  const description = symbol
    ? `${companyName ? `${companyName} (${symbol})` : symbol} stock grade${grade ? ` (${grade})` : ''} with technical indicators and fundamentals. ${asOf ? `As of ${asOf}. ` : ''}Powered by RankAlpha.`
    : 'RankAlpha ticker workspace.'

  return {
    title,
    description,
    alternates: { canonical: canonicalUrl },
    robots: { index: true, follow: true },
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
    keywords: symbol
      ? [
          symbol,
          ...(companyName ? [companyName] : []),
          'stock grade',
          'technical indicators',
          'fundamentals',
          'momentum',
          'value',
          'sentiment',
          'RankAlpha',
        ]
      : ['RankAlpha', 'ticker workspace'],
  }
}

export default async function TickerWorkspacePage({
  params,
  searchParams,
}: {
  params: { symbol: string }
  searchParams?: { [key: string]: string | string[] | undefined }
}) {
  const rawTab = searchParams?.tab
  const tabValue = Array.isArray(rawTab) ? rawTab[0] : rawTab
  const tab = tabValue || 'summary'
  const rawIncludeSetups = searchParams?.include_setups
  const includeSetupsValue = Array.isArray(rawIncludeSetups) ? rawIncludeSetups[0] : rawIncludeSetups
  const includeSetups =
    includeSetupsValue === undefined
      ? true
      : includeSetupsValue === '1' || includeSetupsValue === 'true'
  return (
    <div className="space-y-4">
      <TickerTabMemory tabs={['summary', 'technicals', 'setups', 'ai', 'peers']} />
      <PrimaryBackLink kind="ticker" />
      <StockDetailView symbol={params.symbol} variant="page" tab={tab} includeSetups={includeSetups} />
    </div>
  )
}
