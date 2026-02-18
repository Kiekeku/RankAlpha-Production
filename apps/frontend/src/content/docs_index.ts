import { methodologyData } from '@/content/screener-methodology'
import { slugify } from '@/lib/slug'

export type DocsIndexHeading = {
  id: string
  label: string
  snippet?: string
}

export type DocsIndexPage = {
  title: string
  href: string
  description: string
  headings: DocsIndexHeading[]
}

const screenerHeadings = methodologyData.map((section) => ({
  id: `section-${slugify(section.title)}`,
  label: section.title,
  snippet: section.intro,
}))

export const DOCS_INDEX: DocsIndexPage[] = [
  {
    title: 'Methodology',
    href: '/methodology',
    description: 'How to read factors, grades, and screeners.',
    headings: [
      { id: 'factors', label: 'Factors (Momentum / Value / Sentiment)' },
      { id: 'screeners', label: 'Screeners (Styles and Consensus)' },
    ],
  },
  {
    title: 'Factor Methodology',
    href: '/about/factors',
    description: 'Detailed walk-through of Momentum, Value, and Sentiment calculations.',
    headings: [
      { id: 'momentum', label: 'Momentum (price trend)' },
      { id: 'value', label: 'Value (fundamentals, cheaper is better)' },
      { id: 'sentiment', label: 'Sentiment (optional)' },
      { id: 'composite', label: 'Composite, Weights, Grades' },
    ],
  },
  {
    title: 'Risk Nowcast',
    href: '/about/nowcast',
    description: 'How the daily Nowcast translates cross-asset inputs into an equity drawdown risk score.',
    headings: [
      { id: 'overview', label: 'Overview' },
      { id: 'computation', label: 'How it’s computed' },
      { id: 'pillars', label: 'Headline pillars' },
      { id: 'peripheral', label: 'Peripheral signals' },
      { id: 'data', label: 'Data & API' },
    ],
  },
  {
    title: 'Regime Detection',
    href: '/about/regime',
    description: 'How we infer risk-on/risk-off from screener breadth and intensity.',
    headings: [
      { id: 'regime-detection', label: 'Regime Detection' },
      { id: 'rank-regime', label: 'Rank Regime (Momentum ↔ Value)' },
    ],
  },
  {
    title: 'Screener Methodology',
    href: '/about/screeners',
    description: 'Pre-built screener logic, decays, bonuses, and composite.',
    headings: screenerHeadings,
  },
  {
    title: 'AI Memos',
    href: '/about/ai-analysis',
    description: 'How AI memos, targets, scenarios, and summaries are generated.',
    headings: [
      { id: 'overview', label: 'Overview' },
      { id: 'inputs', label: 'Inputs' },
      { id: 'outputs', label: 'Outputs' },
      { id: 'quality', label: 'Quality & limits' },
      { id: 'cadence', label: 'Refresh cadence' },
    ],
  },
  {
    title: 'Pipeline Health',
    href: '/about/pipeline',
    description: 'Live ingestion, scoring, and sentiment job status plus refresh cadence.',
    headings: [
      { id: 'overview', label: 'Pipeline overview' },
      { id: 'status', label: 'Component status' },
    ],
  },
  {
    title: 'Architecture',
    href: '/about/architecture',
    description: 'Data flow, services, and storage layers.',
    headings: [
      { id: 'diagram', label: 'Architecture diagram' },
      { id: 'flow', label: 'Data flow' },
    ],
  },
]
