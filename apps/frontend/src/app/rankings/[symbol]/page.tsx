import type { Metadata } from 'next'
import { buildUpstreamUrl } from '@/app/api/_utils/upstream'
import type { AssetDetail } from '@/lib/api'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { redirect } from 'next/navigation'

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
    symbol || 'Stock',
    companyName || undefined,
    grade ? `Grade ${grade}` : undefined,
  ].filter(Boolean)
  const title = titleParts.join(' - ')

  const description = symbol
    ? `${companyName ? `${companyName} (${symbol})` : symbol} stock grade${grade ? ` (${grade})` : ''} with technical indicators and fundamentals. ${asOf ? `As of ${asOf}. ` : ''}Powered by RankAlpha.`
    : 'RankAlpha stock details page.'

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
      : ['RankAlpha', 'stock details'],
  }
}

export default async function RankingsSymbolPage({
  params,
  searchParams,
}: {
  params: { symbol: string }
  searchParams?: { [key: string]: string | string[] | undefined }
}) {
  const rawTab = searchParams?.tab
  const tab = Array.isArray(rawTab) ? rawTab[0] : rawTab
  const symbol = (params.symbol || '').trim().toUpperCase()
  const base = symbol ? `/ticker/${encodeURIComponent(symbol)}` : '/ticker'
  if (tab) {
    const params = new URLSearchParams()
    params.set('tab', tab)
    redirect(`${base}?${params.toString()}`)
  }
  redirect(base)
}
