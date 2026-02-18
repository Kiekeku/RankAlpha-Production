import { Metadata } from 'next'
import Link from 'next/link'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DataTable } from '@/components/ui/data-table'
import { ColumnHeaderTooltip } from '@/components/column-header-tooltip'
import { Badge } from '@/components/ui/badge'
import { adminApiFetch } from '@/lib/server/admin_api'
import { requireAdminSession } from '@/lib/server/require_admin'
import { getIntSearchParam } from '@/lib/server/search_params'

type Nullable<T> = T | null | undefined

interface NewswireRawItem {
  raw_id: string
  is_centroid: boolean
  source_domain: Nullable<string>
  title: Nullable<string>
  snippet: Nullable<string>
  published_at: Nullable<string>
  first_seen_ts: Nullable<string>
  url: Nullable<string>
  body_fetch_status: Nullable<string>
  body_fetch_ts: Nullable<string>
  body_source: Nullable<string>
  body_bytes: Nullable<number>
  language: Nullable<string>
  country: Nullable<string>
}

interface NewswireImpactItem {
  stock_key: number
  symbol: Nullable<string>
  company_name: Nullable<string>
  role: Nullable<string>
  confidence: Nullable<number>
  direction: Nullable<string>
  magnitude_score: Nullable<number>
}

interface NewswireEventItem {
  event_id: string
  decided_at: string
  cluster_id: string
  cluster_first_seen: Nullable<string>
  centroid_raw_id: Nullable<string>
  materiality_score: number
  prefilter_score: number
  prefilter_reason: Nullable<string>
  summary: Nullable<string>
  llm_status: string
  llm_model: Nullable<string>
  llm_ran_at: Nullable<string>
  llm_error: Nullable<string>
  sources: string[]
  impacts: NewswireImpactItem[]
  raw_items: NewswireRawItem[]
}

interface NewswireEventsResponse {
  items: NewswireEventItem[]
  count: number
}

type TimelineRow = {
  key: string
  step: string
  timestamp: Nullable<string>
  context: string
  details: string
  hint?: string
}

export const metadata: Metadata = {
  title: 'Newswire Trace | RankAlpha',
}

function formatDate(value: Nullable<string>) {
  if (!value) {
    return '-'
  }
  try {
    return new Date(value).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZoneName: 'short',
    })
  } catch {
    return value
  }
}

function formatScore(value: Nullable<number>, fractionDigits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '0.00'
  }
  return value.toFixed(fractionDigits)
}

function formatBodyStatus(item: NewswireRawItem) {
  if (!item.body_fetch_status) {
    return 'not requested'
  }
  const normalized = item.body_fetch_status.replace(/_/g, ' ')
  const parts = [normalized]
  if (item.body_bytes) {
    parts.push(`${item.body_bytes.toLocaleString()} bytes`)
  }
  if (item.body_source) {
    parts.push(`via ${item.body_source}`)
  }
  return parts.join(' · ')
}

function buildTimelineRows(event: NewswireEventItem): TimelineRow[] {
  const rows: TimelineRow[] = []

  event.raw_items.forEach((raw, index) => {
    rows.push({
      key: `${event.event_id}-raw-${raw.raw_id}-${index}`,
      step: raw.is_centroid ? 'Cluster Centroid' : 'Collector Hit',
      timestamp: raw.first_seen_ts ?? raw.published_at,
      context: raw.source_domain ?? 'Unknown source',
      details: raw.title
        ? `${raw.title}${raw.snippet ? ` - ${raw.snippet}` : ''}`
        : raw.snippet ?? 'No headline captured.',
      hint: formatBodyStatus(raw),
    })
  })

  rows.push({
    key: `${event.event_id}-prefilter`,
    step: 'Prefilter',
    timestamp: event.decided_at,
    context: `Materiality ${formatScore(event.materiality_score, 1)}`,
    details: event.prefilter_reason || 'Prefilter reason unavailable.',
  })

  rows.push({
    key: `${event.event_id}-llm`,
    step: 'LLM',
    timestamp: event.llm_ran_at,
    context: `Status: ${event.llm_status}`,
    details: event.llm_model ? `Model ${event.llm_model}` : 'No model recorded.',
    hint: event.llm_error || undefined,
  })

  return rows
}

export default async function AdminNewswirePage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[]>
}) {
  await requireAdminSession('/admin?notice=error&message=Not%20authorized', {
    attemptedPath: '/admin/newswire',
    method: 'GET',
  })

  const limit = getIntSearchParam(searchParams, 'limit', { min: 1, max: 100 }) ?? 20
  const hours = getIntSearchParam(searchParams, 'hours', { min: 1, max: 168 }) ?? 24

  const query = new URLSearchParams()
  query.set('limit', String(limit))
  if (hours) {
    query.set('hours', String(hours))
  }

  let data: NewswireEventsResponse | null = null
  let loadError: string | null = null
  try {
    const result = await adminApiFetch<NewswireEventsResponse>(
      `/api/v1/admin/newswire/events?${query.toString()}`,
      { method: 'GET' },
      { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' },
    )
    if (!result.ok || !result.payload) {
      throw new Error(result.message || 'Failed to load newswire events.')
    }
    data = result.payload
  } catch (err: any) {
    loadError = err instanceof Error ? err.message : 'Failed to load newswire events.'
    data = { items: [], count: 0 }
  }

  const events = data?.items ?? []

  return (
    <div className="container space-y-6 py-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Newswire Trace</h1>
          <p className="mt-1 text-muted-foreground">
            Inspect the collector → dedup → prefilter flow before enabling LLM or sentiment handoffs.
          </p>
        </div>
        <Link
          href="/admin"
          className="inline-flex items-center rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
        >
          Back to Admin
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="flex flex-wrap items-end gap-4 text-sm" method="get">
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Lookback hours</span>
              <input
                type="number"
                name="hours"
                min={1}
                max={168}
                defaultValue={hours}
                className="mt-1 w-24 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
              />
            </label>
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Event limit</span>
              <input
                type="number"
                name="limit"
                min={1}
                max={100}
                defaultValue={limit}
                className="mt-1 w-24 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
              />
            </label>
            <button
              type="submit"
              className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              Apply
            </button>
          </form>
        </CardContent>
      </Card>

      {loadError ? (
        <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
          {loadError}
        </div>
      ) : null}

      {events.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No events in window</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Adjust the filters or wait for the collector to ingest more stories.
          </CardContent>
        </Card>
      ) : null}

      {events.map((event) => {
        const rows = buildTimelineRows(event)
        const symbols = Array.from(
          new Set(
            event.impacts
              .map((impact) => (impact.symbol ? impact.symbol.toUpperCase() : null))
              .filter((sym): sym is string => Boolean(sym)),
          ),
        )

        return (
          <Card key={event.event_id}>
            <CardHeader className="space-y-2">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <CardTitle className="text-xl font-semibold text-foreground">
                    {formatDate(event.decided_at)}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Materiality {formatScore(event.materiality_score, 1)} · Prefilter {formatScore(event.prefilter_score, 3)}
                    {event.sources.length ? ` · Sources: ${event.sources.join(', ')}` : ''}
                  </p>
                  {event.summary ? (
                    <p className="text-sm text-foreground">{event.summary}</p>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  {symbols.length ? symbols.map((sym) => (
                    <Badge key={sym} variant="secondary">
                      {sym}
                    </Badge>
                  )) : (
                    <Badge variant="outline">No ticker mapped</Badge>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <DataTable className="table-auto border-collapse">
                  <thead>
                    <tr className="bg-muted/40 text-left">
                      <th className="px-3 py-2 font-medium text-foreground">
                        <ColumnHeaderTooltip label="Step" tooltipKey="admin.newswire.step" />
                      </th>
                      <th className="px-3 py-2 font-medium text-foreground">
                        <ColumnHeaderTooltip label="Timestamp" tooltipKey="admin.newswire.timestamp" />
                      </th>
                      <th className="px-3 py-2 font-medium text-foreground">
                        <ColumnHeaderTooltip label="Source / Ticker" tooltipKey="admin.newswire.source" />
                      </th>
                      <th className="px-3 py-2 font-medium text-foreground">
                        <ColumnHeaderTooltip label="Details" tooltipKey="admin.newswire.details" />
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.key} className="border-b border-border/60 last:border-b-0">
                        <td className="align-top px-3 py-2 font-medium text-foreground">{row.step}</td>
                        <td className="align-top px-3 py-2 text-muted-foreground">{formatDate(row.timestamp)}</td>
                        <td className="align-top px-3 py-2 text-foreground">{row.context}</td>
                        <td className="align-top px-3 py-2 text-foreground">
                          <div className="space-y-1">
                            <div>{row.details}</div>
                            {row.hint ? <div className="text-xs text-muted-foreground">{row.hint}</div> : null}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
