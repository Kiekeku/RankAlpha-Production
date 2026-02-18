'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { DocsHeading } from '@/components/docs/docs-heading'
import { DocsLayout } from '@/components/docs/docs-layout'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ActivityIcon, Info } from 'lucide-react'
import { formatEasternDate, formatEasternDateTime, formatEasternTime } from '@/lib/date'

export default function PipelinePage() {
  const { data: pipeline, isLoading } = useQuery({
    queryKey: ['pipeline-health'],
    queryFn: () => api.getPipelineHealth(),
  })

  return (
    <DocsLayout
      title="Pipeline Health"
      subtitle="Live ingestion, scoring, and sentiment job status plus refresh cadence."
      toc={[
        { id: 'overview', label: 'Pipeline overview' },
        { id: 'status', label: 'Component status' },
      ]}
      backHref="/about"
      backLabel="Back to About overview"
    >
      <section id="overview" className="space-y-3">
        <DocsHeading id="overview" level={2} className="text-2xl">
          Pipeline Overview
        </DocsHeading>
        <p className="text-sm text-muted-foreground">How ingestion, scoring, and sentiment work together.</p>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Link href="/overview" className="rounded-full border border-outline/10 bg-card px-3 py-1 font-semibold text-muted-foreground hover:text-foreground">
            Open Overview Dashboard
          </Link>
        </div>
        <Card>
          <CardContent className="space-y-4 text-sm leading-relaxed text-muted-foreground">
            <div className="flex items-start gap-3 rounded-2xl border border-border/60 bg-background/70 p-3 sm:gap-4 sm:p-4">
              <div className="rounded-full bg-primary/10 p-2 text-primary">
                <ActivityIcon className="h-4 w-4" />
              </div>
              <div className="space-y-1 text-foreground">
                <p className="font-medium">End-to-end refresh</p>
                <p className="text-muted-foreground">
                  Ingestion writes canonical Parquet + technicals, Scorer updates momentum/value and weights, Sentiment agents post AI
                  factors, and the API clears caches/materialized views so the frontend reflects fresh data.
                </p>
              </div>
            </div>
            <ul className="list-disc space-y-1 pl-5">
              <li>Ingestion runs nightly (~6:30 pm ET) to capture OHLCV and recompute technical indicators.</li>
              <li>Scorer follows ingestion, refreshing momentum, valuation, and hybrid weights.</li>
              <li>Sentiment agents execute hourly during market hours with budget guardrails.</li>
              <li>API + frontend caches flush when scorer/sentiment complete or on manual refresh.</li>
            </ul>
          </CardContent>
        </Card>
      </section>

      <section id="status" className="space-y-3">
        <DocsHeading id="status" level={2} className="text-2xl">
          Component Status
        </DocsHeading>
        <p className="text-sm text-muted-foreground">Live job telemetry and last run metadata.</p>
        <Card>
          <CardContent>
            <div className="mb-4 flex items-center gap-2 rounded-full border border-border/60 bg-background/80 px-3 py-2">
              <Info className="h-3.5 w-3.5 text-muted-foreground" />
              {isLoading ? (
                <Skeleton className="h-4 w-20" />
              ) : (
                <div className="text-xs">
                  <span className="font-semibold uppercase tracking-wide">
                    {pipeline?.overall_status ?? 'UNKNOWN'}
                  </span>
                  <span className="ml-2 text-muted-foreground">
                    Last check: {pipeline?.last_check ? formatEasternTime(pipeline.last_check) : 'N/A'}
                  </span>
                </div>
              )}
            </div>
            {isLoading ? (
              <div className="space-y-3 sm:space-y-4">
                {[...Array(3)].map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : (
              <div className="space-y-3 sm:space-y-4">
                {pipeline?.components?.map((component: any) => (
                  <div
                    key={component.component}
                    className="flex flex-col gap-2.5 rounded-2xl border border-border/60 bg-background/70 p-3 transition hover:border-primary/40 hover:bg-background/80 sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:p-4"
                  >
                    <div className="flex items-start gap-3 sm:items-center sm:gap-4">
                      <div className={`h-2 w-2 rounded-full ${getStatusColor(component.status)}`} />
                      <div>
                        <p className="font-medium capitalize text-foreground">{component.component}</p>
                        <p className="text-sm text-muted-foreground">{component.message}</p>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 gap-1 text-sm sm:text-right">
                      {typeof component.gap_bdays === 'number' && component.gap_bdays > 1 && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <p className={component.gap_bdays > 3 ? 'text-red-500 cursor-help' : 'text-yellow-600 cursor-help'}>
                              Gap: {component.gap_bdays} business day{component.gap_bdays === 1 ? '' : 's'}
                            </p>
                          </TooltipTrigger>
                          <TooltipContent side="left" align="center">
                            {renderThresholdTooltip(component.component, pipeline)}
                          </TooltipContent>
                        </Tooltip>
                      )}
                      {component.component === 'ingestion' && component.price_latest_date && (
                        <p className="text-muted-foreground">Price date: {formatEasternDate(component.price_latest_date)}</p>
                      )}
                      {component.component === 'ingestion' && component.screener_last_run && (
                        <p className="text-muted-foreground">Screener run: {formatEasternDateTime(component.screener_last_run)}</p>
                      )}
                      {component.last_run && <p>Last run: {formatEasternDateTime(component.last_run)}</p>}
                      {component.records_processed !== null && component.records_processed !== undefined && (
                        <p className="text-muted-foreground">{component.records_processed} records</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </DocsLayout>
  )
}

function getStatusColor(status: string) {
  switch (status) {
    case 'healthy':
      return 'bg-green-500'
    case 'warning':
      return 'bg-yellow-500'
    case 'error':
      return 'bg-red-500'
    default:
      return 'bg-gray-500'
  }
}

function renderThresholdTooltip(component: string, pipeline?: any) {
  const t = pipeline?.thresholds
  if (!t) return 'No threshold data'
  switch (component) {
    case 'ingestion':
      return `Healthy ≤ ${t.ingestion_healthy_max_bdays} bd • Warning ≤ ${t.ingestion_warning_max_bdays} bd • Error beyond`
    case 'scorer':
      return `Healthy ≤ ${t.scorer_healthy_max_bdays} bd • Warning beyond`
    case 'sentiment':
      return `Healthy ≤ ${t.sentiment_healthy_max_bdays} bd • Warning beyond`
    default:
      return 'Health thresholds vary by component'
  }
}
