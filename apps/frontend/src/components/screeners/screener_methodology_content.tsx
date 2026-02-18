import Link from 'next/link'

import { DocsHeading } from '@/components/docs/docs-heading'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { methodologyData } from '@/content/screener-methodology'
import { slugify } from '@/lib/slug'

export function ScreenerMethodologyContent({ showInlineToc = true }: { showInlineToc?: boolean }) {
  return (
    <div className="space-y-4">
      <Card className="border-outline/10">
        <CardHeader>
          <CardTitle>Guide and Reference</CardTitle>
          <CardDescription>Styles, decay math, bonuses, and the 0–100 consensus composite.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-6 text-sm leading-relaxed">
            {showInlineToc ? (
              <nav aria-label="Screener methodology sections" className="flex flex-wrap gap-2">
                {methodologyData.map((section) => {
                  const id = `section-${slugify(section.title)}`
                  return (
                    <a
                      key={id}
                      href={`#${id}`}
                      className="rounded-full border border-outline/10 bg-secondary/10 px-3 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                    >
                      {section.title}
                    </a>
                  )
                })}
              </nav>
            ) : null}

            <div className="rounded-xl border border-status-info/25 bg-status-info/10 p-3 text-xs text-status-info-foreground">
              <div className="font-semibold text-status-info-foreground">How this shows up in the product</div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-status-info-foreground/90">
                <li>
                  In <span className="font-semibold">Screener - Results</span>, Consensus and Primary summarize cross-screener agreement for quick triage.
                </li>
                <li>
                  In <span className="font-semibold">Screener - Movements</span>, “New entrants / Re-entries / Drops” show confirmed changes after a short window.
                </li>
                <li>
                  In <span className="font-semibold">Overview</span>, breadth and intensity help drive regime labels like Trend, Chop, and Risk-Off.
                </li>
              </ul>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Link href="/screener" className="rounded-full border border-status-info/25 bg-card px-2.5 py-1 text-[11px] font-semibold text-status-info-foreground hover:underline">
                  See Screener Results
                </Link>
                <Link href="/overview/regime" className="rounded-full border border-status-info/25 bg-card px-2.5 py-1 text-[11px] font-semibold text-status-info-foreground hover:underline">
                  See Regime Dashboard
                </Link>
              </div>
            </div>

            {methodologyData.map((section) => (
              <section key={section.title} id={`section-${slugify(section.title)}`} className="space-y-3 scroll-mt-24">
                <DocsHeading id={`section-${slugify(section.title)}`} level={3} className="text-base">
                  {section.title}
                </DocsHeading>
                {section.intro ? <p className="text-muted-foreground">{section.intro}</p> : null}
                {section.paragraphs?.map((paragraph, idx) => (
                  <p key={idx}>{paragraph}</p>
                ))}
                {section.groups?.map((group) => (
                  <div key={group.title} className="space-y-3">
                    <h4 className="text-sm font-semibold text-foreground">{group.title}</h4>
                    <div className="space-y-3">
                      {group.screeners.map((screener) => (
                        <div key={screener.name} className="rounded-lg border border-outline/10 bg-secondary/10 p-3">
                          <p className="text-sm font-semibold">{screener.name}</p>
                          <p className="mt-1 text-muted-foreground">{screener.goal}</p>
                          <p className="mt-1">{screener.criteria}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                {section.subsections?.map((sub) => (
                  <div key={sub.subtitle} className="space-y-2">
                    <h4 className="text-sm font-semibold text-foreground">{sub.subtitle}</h4>
                    {sub.paragraphs?.map((paragraph, idx) => (
                      <p key={idx}>{paragraph}</p>
                    ))}
                    {sub.code ? (
                      <pre className="whitespace-pre-wrap rounded-md border border-outline/10 bg-secondary/10 p-3 text-xs font-mono text-muted-foreground">
                        {sub.code.join('\n')}
                      </pre>
                    ) : null}
                    {sub.bullets ? (
                      <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                        {sub.bullets.map((item, idx) => (
                          <li key={idx}>{item}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))}
                {section.bullets ? (
                  <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                    {section.bullets.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {section.qa?.map((entry) => (
                  <div key={entry.question} className="rounded-lg border border-outline/10 bg-secondary/10 p-3">
                    <p className="text-sm font-semibold">{entry.question}</p>
                    <p className="mt-1 text-muted-foreground">{entry.answer}</p>
                  </div>
                ))}
              </section>
            ))}

            <div className="rounded-xl border border-outline/10 bg-secondary/10 p-3 text-xs text-muted-foreground">
              <div className="font-semibold text-foreground">How to use this</div>
              <div className="mt-1">
                Use the TOC to jump to the style family or math section you care about, then sanity-check the same labels in the Screener UI (Consensus, Appear, Styles, Sources, Best %ile).
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
