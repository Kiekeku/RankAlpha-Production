import { DocsLayout } from '@/components/docs/docs-layout'
import { FactorMethodologyContent } from '@/components/factors/factor_methodology_content'

export default function FactorsPage() {
  return (
    <DocsLayout
      title="Factor Methodology"
      subtitle="Momentum, Value, and Sentiment calculations"
      toc={[
        { id: 'momentum', label: 'Momentum' },
        { id: 'value', label: 'Value' },
        { id: 'sentiment', label: 'Sentiment' },
        { id: 'composite', label: 'Composite & Grades' },
      ]}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <FactorMethodologyContent showInlineToc={false} />
    </DocsLayout>
  )
}
