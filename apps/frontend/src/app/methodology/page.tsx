import type { Metadata } from 'next'

import { DocsLayout } from '@/components/docs/docs-layout'
import { FactorMethodologyContent } from '@/components/factors/factor_methodology_content'
import { ScreenerMethodologyContent } from '@/components/screeners/screener_methodology_content'

export const metadata: Metadata = {
  title: 'Methodology',
  description: 'Factor and screener methodology for RankAlpha.',
}

export default function MethodologyPage() {
  return (
    <DocsLayout
      title="Methodology"
      subtitle="How to read factors, grades, and screeners"
      toc={[
        { id: 'factors', label: 'Factors (Momentum / Value / Sentiment)' },
        { id: 'screeners', label: 'Screeners (Styles and Consensus)' },
      ]}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <section id="factors" className="scroll-mt-24">
        <FactorMethodologyContent showInlineToc={false} />
      </section>
      <section id="screeners" className="scroll-mt-24">
        <ScreenerMethodologyContent showInlineToc={false} />
      </section>
    </DocsLayout>
  )
}
