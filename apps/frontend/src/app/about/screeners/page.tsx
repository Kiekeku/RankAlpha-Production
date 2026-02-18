import { DocsLayout } from '@/components/docs/docs-layout'
import { ScreenerMethodologyContent } from '@/components/screeners/screener_methodology_content'
import { methodologyData } from '@/content/screener-methodology'
import { slugify } from '@/lib/slug'

export default function ScreenerMethodologyPage() {
  const toc = methodologyData.map((section) => ({
    id: `section-${slugify(section.title)}`,
    label: section.title,
  }))

  return (
    <DocsLayout
      title="Screener Methodology"
      subtitle="Styles, decay math, bonuses, and the 0–100 consensus composite."
      toc={toc}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <ScreenerMethodologyContent showInlineToc={false} />
    </DocsLayout>
  )
}
