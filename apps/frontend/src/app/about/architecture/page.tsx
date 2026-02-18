import { ArchitectureDiagram } from '@/components/about/architecture_diagram'
import { DocsHeading } from '@/components/docs/docs-heading'
import { DocsLayout } from '@/components/docs/docs-layout'

export default async function ArchitectureDocPage() {
  return (
    <DocsLayout
      title="Architecture"
      subtitle="Data flow, services, and storage layers."
      toc={[
        { id: 'diagram', label: 'Architecture diagram' },
        { id: 'flow', label: 'Data flow' },
      ]}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <section id="diagram" className="space-y-3">
        <DocsHeading id="diagram" level={2} className="text-2xl">
          Architecture diagram
        </DocsHeading>
        <ArchitectureDiagram title="RankAlpha Architecture" />
      </section>

      <section id="flow" className="space-y-3">
        <DocsHeading id="flow" level={2} className="text-2xl">
          Data flow
        </DocsHeading>
        <p className="text-sm text-muted-foreground">
          Prices → ingestion → scorer → AI sentiment → API → frontend. Use this diagram alongside Pipeline Health for live freshness checks.
        </p>
      </section>
    </DocsLayout>
  )
}
