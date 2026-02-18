'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, type PipelineHealth } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { formatEasternDateTime } from '@/lib/date'

function isHealthyStatus(status?: string | null) {
  const raw = (status || '').trim().toLowerCase()
  if (!raw) return false
  return raw.includes('healthy') || raw.includes('ok') || raw.includes('success')
}

function isOutageStatus(status?: string | null) {
  const raw = (status || '').trim().toLowerCase()
  if (!raw) return false
  return raw.includes('outage') || raw.includes('error') || raw.includes('down')
}

function resolveStatusLabel(status?: string | null) {
  if (isHealthyStatus(status)) return 'OK'
  if (isOutageStatus(status)) return 'Outage'
  return 'Degraded'
}

function resolveAggregateStatus(
  components: PipelineHealth['components'] | undefined,
  overall?: string | null,
) {
  if (components && components.length) {
    let hasDegraded = false
    for (const component of components) {
      const status = component?.status
      if (isOutageStatus(status)) return 'Outage'
      if (!isHealthyStatus(status)) hasDegraded = true
    }
    if (hasDegraded) return 'Degraded'
    return 'OK'
  }
  return resolveStatusLabel(overall)
}

const COMPONENT_LABELS: Record<string, string> = {
  ingestion: 'Prices + technicals',
  scorer: 'Grades + weights',
  sentiment: 'AI targets + sentiment',
}

export function DataStatusIndicator({ className }: { className?: string }) {
  const { data } = useQuery<PipelineHealth>({
    queryKey: ['pipeline-health'],
    queryFn: () => api.getPipelineHealth(),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })

  const [open, setOpen] = useState(false)
  const label = resolveAggregateStatus(data?.components, data?.overall_status)
  const healthy = label === 'OK'
  const affected = useMemo(() => {
    return (data?.components ?? []).filter((component) => !isHealthyStatus(component.status))
  }, [data?.components])
  const lastSuccessful = useMemo(() => {
    const healthyRuns = (data?.components ?? [])
      .filter((component) => isHealthyStatus(component.status) && component.last_run)
      .map((component) => component.last_run as string)
    if (healthyRuns.length) {
      return healthyRuns.reduce((acc, d) => (new Date(d) > new Date(acc) ? d : acc), healthyRuns[0])
    }
    const allRuns = (data?.components ?? [])
      .map((component) => component.last_run)
      .filter((value): value is string => Boolean(value))
    if (allRuns.length) {
      return allRuns.reduce((acc, d) => (new Date(d) > new Date(acc) ? d : acc), allRuns[0])
    }
    return data?.last_check ?? null
  }, [data])

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          'inline-flex items-center gap-2 rounded-full border border-outline/10 bg-card px-3 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-outline/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          className,
        )}
        aria-label={`Data status ${label}`}
      >
        <span
          aria-hidden
          className={cn(
            'inline-block h-2 w-2 rounded-full',
            healthy ? 'bg-status-success' : label === 'Outage' ? 'bg-status-danger' : 'bg-status-warning',
          )}
        />
        <span>Data:</span>
        <span className={cn(healthy ? 'text-status-success' : label === 'Outage' ? 'text-status-danger' : 'text-status-warning')}>
          {label}
        </span>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Data Status</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-outline/10 bg-secondary/10 px-3 py-2 text-xs font-semibold text-muted-foreground">
              <span>Status</span>
              <span className={cn(
                healthy ? 'text-status-success' : label === 'Outage' ? 'text-status-danger' : 'text-status-warning'
              )}>
                {label}
              </span>
              {data?.last_check ? (
                <span className="text-muted-foreground">Last check {formatEasternDateTime(data.last_check)}</span>
              ) : null}
            </div>

            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Affected modules</div>
              {affected.length ? (
                <ul className="space-y-2">
                  {affected.map((component) => {
                    const name = component.component || 'unknown'
                    const labelText = COMPONENT_LABELS[name] ?? name
                    return (
                      <li key={name} className="rounded-xl border border-outline/10 bg-card px-3 py-2">
                        <div className="text-sm font-semibold text-foreground">{labelText}</div>
                        <div className="text-xs text-muted-foreground">
                          {component.message || component.status || 'Status degraded'}
                        </div>
                        {component.last_run ? (
                          <div className="text-[11px] text-muted-foreground">
                            Last run {formatEasternDateTime(component.last_run)}
                          </div>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              ) : (
                <div className="rounded-xl border border-outline/10 bg-card px-3 py-2 text-xs text-muted-foreground">
                  No affected modules detected.
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Last successful refresh</div>
              <div className="rounded-xl border border-outline/10 bg-card px-3 py-2 text-xs text-muted-foreground">
                {lastSuccessful ? formatEasternDateTime(lastSuccessful) : 'Unknown'}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Expected cadence</div>
              <ul className="space-y-1 text-xs text-muted-foreground">
                <li>Ingestion: nightly after US close.</li>
                <li>Scorer: nightly after ingestion.</li>
                <li>Sentiment: hourly during market hours.</li>
              </ul>
            </div>

            <div className="flex items-center justify-between gap-2">
              <Link
                href="/about/pipeline"
                className="text-xs font-semibold text-primary hover:underline"
              >
                Status / Docs
              </Link>
              <button
                type="button"
                className="text-xs font-semibold text-muted-foreground hover:text-foreground"
                onClick={() => setOpen(false)}
              >
                Close
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
