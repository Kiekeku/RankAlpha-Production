import { Metadata } from 'next'
import Link from 'next/link'

import { FlashNotice } from '@/components/flash_notice'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DataTable } from '@/components/ui/data-table'
import { formatEasternDate, formatEasternDateTime } from '@/lib/date'
import { adminApiFetch } from '@/lib/server/admin_api'
import { parseFlashNotice, redirectWithFlashNotice } from '@/lib/server/flash_notice'
import { requireAdminSession } from '@/lib/server/require_admin'
import { getFirstSearchParamTrimmed, getIntSearchParam } from '@/lib/server/search_params'

type Nullable<T> = T | null | undefined

type SentimentQueueItem = {
  queue_id: string
  symbol: string
  stock_key: number
  status: string
  priority: number
  enqueue_ts: Nullable<string>
  run_after_ts: Nullable<string>
  started_ts: Nullable<string>
  completed_ts: Nullable<string>
  attempts: number
  event_id: Nullable<string>
  title: Nullable<string>
  url: Nullable<string>
  source: Nullable<string>
  force_run: boolean
  raw_id: Nullable<string>
  last_analysis_date: Nullable<string>
  last_analysis_id: Nullable<string>
}

type SentimentQueueResponse = {
  total: number
  items: SentimentQueueItem[]
  pending_ready?: number
  pending_future?: number
  last_processed_ts?: Nullable<string>
  last_processed_symbol?: Nullable<string>
}

const STATUS_OPTIONS = ['pending', 'in_progress', 'done', 'failed'] as const
type QueueStatus = (typeof STATUS_OPTIONS)[number]
const SORT_OPTIONS = [
  { value: 'enqueue_ts', label: 'Enqueued' },
  { value: 'run_after_ts', label: 'Run after' },
  { value: 'priority', label: 'Priority' },
  { value: 'last_analysis_date', label: 'Last analysis date' },
  { value: 'completed_ts', label: 'Completed' },
] as const
type SortOption = (typeof SORT_OPTIONS)[number]['value']

export const metadata: Metadata = {
  title: 'Sentiment Queue | Admin | RankAlpha',
}

function normalizeStatus(value: string | undefined): QueueStatus | undefined {
  if (!value) return undefined
  const normalized = value.trim().toLowerCase()
  return (STATUS_OPTIONS as readonly string[]).includes(normalized) ? (normalized as QueueStatus) : undefined
}

function statusBadgeVariant(status: string | null | undefined): 'warning' | 'info' | 'success' | 'danger' | 'outline' {
  switch ((status || '').toLowerCase()) {
    case 'pending':
      return 'warning'
    case 'in_progress':
      return 'info'
    case 'done':
      return 'success'
    case 'failed':
      return 'danger'
    default:
      return 'outline'
  }
}

function formatTimestamp(value: Nullable<string>) {
  return formatEasternDateTime(value, '-')
}

function formatDate(value: Nullable<string>) {
  return formatEasternDate(value, '-')
}

async function enqueueSymbol(formData: FormData) {
  'use server'

  await requireAdminSession('/admin?notice=error&message=Not%20authorized', {
    attemptedPath: '/admin/sentiment-queue',
    method: 'POST',
  })
  const symbol = formData.get('queue_symbol')?.toString().trim().toUpperCase() ?? ''
  const extraParams: Record<string, string> = {}
  const keys = ['status', 'search', 'symbol', 'limit', 'sort_by', 'sort_order', 'include_last']
  keys.forEach((key) => {
    const raw = formData.get(`filter_${key}`)?.toString().trim()
    if (raw) extraParams[key] = raw
  })

  if (!symbol) {
    redirectWithFlashNotice({
      pathname: '/admin/sentiment-queue',
      status: 'error',
      message: 'Provide a symbol to enqueue.',
      extraParams,
    })
  }

  const params = new URLSearchParams()
  params.set('symbol', symbol)
  params.set('force', 'true')
  const result = await adminApiFetch(`/api/v1/admin/news/queue/enqueue?${params.toString()}`, {
    method: 'POST',
  }, { tokenMode: 'service-or-admin' })

  redirectWithFlashNotice({
    pathname: '/admin/sentiment-queue',
    status: result.ok ? 'success' : 'error',
    message: result.ok ? `Enqueued ${symbol} for sentiment analysis.` : result.message,
    extraParams,
  })
}

function normalizeSortBy(value: string | undefined): SortOption {
  const normalized = (value || '').trim().toLowerCase()
  const match = SORT_OPTIONS.find((opt) => opt.value === normalized)
  return match ? match.value : 'enqueue_ts'
}

function normalizeSortOrder(value: string | undefined): 'asc' | 'desc' {
  return value && value.toLowerCase() === 'asc' ? 'asc' : 'desc'
}

export default async function AdminSentimentQueuePage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[]>
}) {
  await requireAdminSession('/admin?notice=error&message=Not%20authorized', {
    attemptedPath: '/admin/sentiment-queue',
    method: 'GET',
  })

  const rawStatus = getFirstSearchParamTrimmed(searchParams, 'status')
  const status = normalizeStatus(rawStatus)
  const search = getFirstSearchParamTrimmed(searchParams, 'search')?.toUpperCase()
  const symbol = getFirstSearchParamTrimmed(searchParams, 'symbol')?.toUpperCase()
  const limit = getIntSearchParam(searchParams, 'limit', { min: 1, max: 1000 }) ?? 200
  const sortBy = normalizeSortBy(getFirstSearchParamTrimmed(searchParams, 'sort_by'))
  const sortOrder = normalizeSortOrder(getFirstSearchParamTrimmed(searchParams, 'sort_order'))
  const includeLastRaw = getFirstSearchParamTrimmed(searchParams, 'include_last')
  const includeLast = includeLastRaw !== 'false' || sortBy === 'last_analysis_date'

  const query = new URLSearchParams()
  if (status) {
    query.set('status', status)
  }
  if (symbol) {
    query.set('symbol', symbol)
  }
  if (!symbol && search) {
    query.set('search', search)
  }
  if (limit) {
    query.set('limit', String(limit))
  }
  if (sortBy) {
    query.set('sort_by', sortBy)
  }
  if (sortOrder) {
    query.set('sort_order', sortOrder)
  }
  if (includeLast) {
    query.set('include_last_analysis', 'true')
  }

  let data: SentimentQueueResponse | null = null
  let loadError: string | null = null
  try {
    const result = await adminApiFetch<SentimentQueueResponse>(
      `/api/v1/admin/news/queue?${query.toString()}`,
      { method: 'GET' },
      { tokenMode: 'service-or-admin', missingTokenMessage: 'AUTH_SERVICE_TOKEN or ADMIN_BEARER_TOKEN not configured' },
    )
    if (!result.ok || !result.payload) {
      throw new Error(result.message || 'Failed to load sentiment queue.')
    }
    data = result.payload
  } catch (err: any) {
    loadError = err instanceof Error ? err.message : 'Failed to load sentiment queue.'
    data = { total: 0, items: [] }
  }

  const items = data?.items ?? []
  const lastProcessed = data?.last_processed_ts ? formatTimestamp(data.last_processed_ts) : '-'
  const lastProcessedSymbol = data?.last_processed_symbol ? String(data.last_processed_symbol).toUpperCase() : null
  const flashNotice = parseFlashNotice(searchParams)

  return (
    <div className="container space-y-6 py-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Sentiment Queue</h1>
          <p className="mt-1 text-muted-foreground">
            Inspect queued sentiment jobs, scheduling, and the latest AI memo per symbol.
          </p>
        </div>
        <Link
          href="/admin"
          className="inline-flex items-center rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
        >
          Back to Admin
        </Link>
      </div>

      {flashNotice ? <FlashNotice status={flashNotice.status} message={flashNotice.message} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>Queue Summary</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <span className="block text-xs uppercase text-muted-foreground">Total rows</span>
            <span className="text-base font-semibold text-foreground">{data?.total?.toLocaleString() ?? '-'}</span>
          </div>
          <div>
            <span className="block text-xs uppercase text-muted-foreground">Ready now</span>
            <span className="text-base font-semibold text-foreground">{data?.pending_ready?.toLocaleString?.() ?? '-'}</span>
          </div>
          <div>
            <span className="block text-xs uppercase text-muted-foreground">Scheduled later</span>
            <span className="text-base font-semibold text-foreground">{data?.pending_future?.toLocaleString?.() ?? '-'}</span>
          </div>
          <div>
            <span className="block text-xs uppercase text-muted-foreground">Last processed</span>
            <span className="text-base font-semibold text-foreground">
              {lastProcessedSymbol ? `${lastProcessedSymbol} • ${lastProcessed}` : lastProcessed}
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="flex flex-wrap items-end gap-4 text-sm" method="get">
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Search symbol</span>
              <input
                type="text"
                name="search"
                defaultValue={search ?? ''}
                className="mt-1 w-40 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                placeholder="AAPL"
              />
            </label>
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Exact symbol</span>
              <input
                type="text"
                name="symbol"
                defaultValue={symbol ?? ''}
                className="mt-1 w-28 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                placeholder="(optional)"
              />
            </label>
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Status</span>
              <select
                name="status"
                defaultValue={status ?? ''}
                className="mt-1 w-40 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
              >
                <option value="">All</option>
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>{opt.replace('_', ' ')}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Limit</span>
              <input
                type="number"
                name="limit"
                min={1}
                max={1000}
                defaultValue={limit}
                className="mt-1 w-28 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
              />
            </label>
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Sort by</span>
              <select
                name="sort_by"
                defaultValue={sortBy}
                className="mt-1 w-44 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
              >
                {SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col">
              <span className="text-xs uppercase text-muted-foreground">Sort order</span>
              <select
                name="sort_order"
                defaultValue={sortOrder}
                className="mt-1 w-32 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
              >
                <option value="desc">Newest first</option>
                <option value="asc">Oldest first</option>
              </select>
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-foreground">
              <input name="include_last" type="checkbox" className="h-4 w-4" defaultChecked={includeLast} />
              Include last AI memo date
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

      <Card>
        <CardHeader>
          <CardTitle>Queue Items</CardTitle>
        </CardHeader>
        <CardContent>
          {loadError ? (
            <p className="text-sm text-destructive">{loadError}</p>
          ) : null}
          <div className="overflow-x-auto">
            <DataTable className="min-w-[980px] table-auto border-collapse">
              <thead>
                <tr className="text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2 pr-4">Symbol</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Priority</th>
                  <th className="py-2 pr-4">Enqueued</th>
                  <th className="py-2 pr-4">Run after</th>
                  <th className="py-2 pr-4">Attempts</th>
                  <th className="py-2 pr-4">Last AI memo</th>
                  <th className="py-2 pr-4">Completed</th>
                  <th className="py-2 pr-4">Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-6 text-center text-sm text-muted-foreground">
                      No queue items found.
                    </td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <tr key={item.queue_id} className="border-t border-border/60 align-top">
                      <td className="py-3 pr-4 font-medium text-foreground">
                        <div className="flex flex-col gap-1">
                          <Link href={`/ai-analysis/${item.symbol}`} className="hover:underline">
                            {item.symbol}
                          </Link>
                          {item.title ? (
                            <span className="line-clamp-2 text-xs text-muted-foreground">{item.title}</span>
                          ) : null}
                        </div>
                      </td>
                      <td className="py-3 pr-4">
                        <Badge variant={statusBadgeVariant(item.status)}>{item.status.replace('_', ' ')}</Badge>
                      </td>
                      <td className="py-3 pr-4">{item.priority?.toLocaleString?.() ?? '0'}</td>
                      <td className="py-3 pr-4">{formatTimestamp(item.enqueue_ts)}</td>
                      <td className="py-3 pr-4">{formatTimestamp(item.run_after_ts)}</td>
                      <td className="py-3 pr-4">{item.attempts ?? 0}</td>
                      <td className="py-3 pr-4">
                        {item.last_analysis_date ? formatDate(item.last_analysis_date) : '-'}
                      </td>
                      <td className="py-3 pr-4">{formatTimestamp(item.completed_ts)}</td>
                      <td className="py-3 pr-4">
                        <form action={enqueueSymbol}>
                          <input type="hidden" name="queue_symbol" value={item.symbol} />
                          <input type="hidden" name="filter_status" value={status ?? ''} />
                          <input type="hidden" name="filter_search" value={search ?? ''} />
                          <input type="hidden" name="filter_symbol" value={symbol ?? ''} />
                          <input type="hidden" name="filter_limit" value={String(limit)} />
                          <input type="hidden" name="filter_sort_by" value={sortBy} />
                          <input type="hidden" name="filter_sort_order" value={sortOrder} />
                          <input type="hidden" name="filter_include_last" value={includeLast ? 'true' : 'false'} />
                          <button
                            type="submit"
                            disabled={(item.status || '').toLowerCase() === 'pending'}
                            className="inline-flex items-center rounded-md border border-border/60 bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Re-queue
                          </button>
                        </form>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </DataTable>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
