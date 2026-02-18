import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Disclaimer | RankAlpha',
  description: 'Important disclosures about RankAlpha data and content.',
}

const sections = [
  {
    heading: 'Informational Purposes Only',
    body: `RankAlpha provides analytics and rankings for research and education. Nothing on this site constitutes investment, trading, accounting, or legal advice, and no recommendation to buy, sell, or hold any security is implied. Always evaluate investments against your own objectives and risk tolerance before acting.`,
  },
  {
    heading: 'No Client Relationship',
    body: `Using RankAlpha does not create an advisory, fiduciary, or brokerage relationship with RankAlpha, its affiliates, or contributors. You remain solely responsible for your own trading decisions and portfolio management.`,
  },
  {
    heading: 'Data Sources & Accuracy',
    body: `Market data, fundamentals, and sentiment inputs are derived from third-party sources that can contain errors, omissions, or delays. RankAlpha believes these sources to be reliable but does not guarantee completeness, timeliness, or accuracy. Scores and grades may change without notice.`,
  },
  {
    heading: 'Forward-Looking Statements',
    body: `Model outputs may reference scenarios or expectations that are inherently uncertain and subject to market, regulatory, and macroeconomic events beyond RankAlpha's control. Past performance is not indicative of future results.`,
  },
  {
    heading: 'Independent Verification',
    body: `Before executing any trade, independently verify price quotes, corporate actions, and other material information. Consult a qualified financial professional if you need advice tailored to your circumstances.`,
  },
]

export default function DisclaimerPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6 sm:space-y-8">
      <header className="space-y-3 sm:space-y-4">
        <p className="text-sm text-muted-foreground">
          Updated September 30, 2025
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Disclaimer</h1>
        <p className="text-base text-muted-foreground sm:text-lg">
          We built RankAlpha to surface systematic insights, but we cannot eliminate risk. Please read these disclosures carefully before relying on any RankAlpha content.
        </p>
      </header>

      <div className="space-y-6">
        {sections.map((section) => (
          <section key={section.heading} className="space-y-2">
            <h2 className="text-xl font-semibold">{section.heading}</h2>
            <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">{section.body}</p>
          </section>
        ))}
      </div>     
    </div>
  )
}
