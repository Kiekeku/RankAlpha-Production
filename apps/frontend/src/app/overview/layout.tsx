import type { Metadata } from 'next'

import { PageHeader } from '@/components/page-header'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { GlossaryDrawer } from '@/components/glossary/glossary_drawer'
import { MethodologyDrawer } from '@/components/methodology/methodology_drawer'
import { OverviewTabs } from '@/components/overview/overview_tabs'
import { OverviewInterpretationBar } from '@/components/overview/overview-interpretation-bar'
import { AudienceHero } from '@/components/audience-hero'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'

export function generateMetadata(): Metadata {
  const siteUrl = getCanonicalSiteUrl()
  const canonicalUrl = `${siteUrl}/overview/nowcast`
  const title = 'RankAlpha - Market Regime & Macro Dashboard'
  const description =
    'Live macro dashboard with risk nowcast, liquidity, funding, credit, volatility, breadth, and sector flows.'

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
      'market regime',
      'macro dashboard',
      'risk nowcast',
      'liquidity',
      'credit spreads',
      'volatility',
      'breadth',
      'sector flows',
      'RankAlpha',
    ],
  }
}

export default function OverviewLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-4 sm:space-y-6">
      <AudienceHero />
      <PageHeader
        title="Macro & Regime Dashboard"
        subtitle="Liquidity, funding, credit, volatility, breadth, and sector flows. Updated nightly."
        contextBadges={['As of latest close', 'Status: live']}
        primaryAction={<PrimaryCtaLink href="/rankings">Go to Rankings</PrimaryCtaLink>}
        secondaryActions={[
          <MethodologyDrawer key="overview-methodology" renderDialog={false} />,
          <GlossaryDrawer key="overview-glossary" renderDialog={false} />,
        ]}
        tabs={<OverviewTabs />}
      />

      {/* Uses React Query; root Providers supply QueryClientProvider. */}
      <OverviewInterpretationBar />

      {children}
    </div>
  )
}
