import { Metadata } from 'next'
import Link from 'next/link'

import { FlashNotice } from '@/components/flash_notice'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatEasternDateTime } from '@/lib/date'
import { adminApiFetch, hasAuthServiceToken } from '@/lib/server/admin_api'
import { parseFlashNotice, redirectWithFlashNotice } from '@/lib/server/flash_notice'
import { requireAdminSession } from '@/lib/server/require_admin'

export const metadata: Metadata = {
  title: 'Admin | RankAlpha',
}

const UNAUTHORIZED_REDIRECT = '/admin?notice=error&message=Not%20authorized'

async function triggerGradesRefresh() {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const result = await adminApiFetch('/api/v1/admin/grades/refresh', { method: 'POST' }, { tokenMode: 'service-or-admin' })
  if (result.ok) {
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: 'Grades refresh triggered successfully.' })
  }
  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function triggerPublicGradesRefresh() {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const result = await adminApiFetch('/api/v1/grading/refresh', { method: 'POST' }, { tokenMode: 'service-or-admin' })
  if (result.ok) {
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: 'Public grading refresh triggered successfully.' })
  }
  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function triggerWeightsRecompute() {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const result = await adminApiFetch('/api/v1/admin/weights/recompute', {
    method: 'POST',
    body: JSON.stringify({ value: true }),
    headers: { 'Content-Type': 'application/json' },
  }, { tokenMode: 'service-or-admin' })
  if (result.ok) {
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: 'Set force_recompute_weights flag to true.' })
  }
  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function previewQueueMaintenance(formData: FormData) {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const includeEvent = formData.get('qm_include_event')?.toString() === 'on'
  const cleanupDone = formData.get('qm_cleanup_done_days')?.toString()?.trim()
  const cleanupFailed = formData.get('qm_cleanup_failed_days')?.toString()?.trim()
  const payload: Record<string, unknown> = {
    dry_run: true,
    include_event_specific: includeEvent,
  }
  if (cleanupDone) payload.cleanup_done_days = Number.parseInt(cleanupDone, 10)
  if (cleanupFailed) payload.cleanup_failed_days = Number.parseInt(cleanupFailed, 10)

  const result = await adminApiFetch('/api/v1/admin/news/queue/maintain', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, { tokenMode: 'service-or-admin' })
  if (result.ok) {
    const p = (result.payload ?? {}) as any
    const msg = `Dry-run: pending dupes=${p.examined_pending ?? 0}, event dupes=${p.examined_event ?? 0}.`
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: msg })
  }
  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function applyQueueMaintenance(formData: FormData) {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const includeEvent = formData.get('qm_include_event')?.toString() === 'on'
  const cleanupDone = formData.get('qm_cleanup_done_days')?.toString()?.trim()
  const cleanupFailed = formData.get('qm_cleanup_failed_days')?.toString()?.trim()
  const payload: Record<string, unknown> = {
    dry_run: false,
    include_event_specific: includeEvent,
  }
  if (cleanupDone) payload.cleanup_done_days = Number.parseInt(cleanupDone, 10)
  if (cleanupFailed) payload.cleanup_failed_days = Number.parseInt(cleanupFailed, 10)

  const result = await adminApiFetch('/api/v1/admin/news/queue/maintain', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, { tokenMode: 'service-or-admin' })
  if (result.ok) {
    const p = (result.payload ?? {}) as any
    const msg = `Applied: deleted pending=${p.deleted_pending_duplicates ?? 0}, event=${p.deleted_event_duplicates ?? 0}, done=${p.deleted_done ?? 0}, failed=${p.deleted_failed ?? 0}.`
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: msg })
  }
  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function triggerPriceCacheRefresh(formData: FormData) {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const rawSymbols = formData.get('symbols')?.toString() ?? ''
  const symbols = rawSymbols
    .split(/[, \n\r\t]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)

  if (!symbols.length) {
    redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: 'Provide at least one symbol to warm the cache.' })
  }

  const reason = formData.get('reason')?.toString().trim() || 'admin-ui'
  const force = formData.get('force')?.toString() === 'on'
  const chunkRaw = formData.get('chunk_size')?.toString().trim()
  const chunkSize = chunkRaw ? Number.parseInt(chunkRaw, 10) : undefined

  const payload: Record<string, unknown> = {
    symbols,
    reason,
    force,
  }
  if (chunkSize && Number.isFinite(chunkSize)) {
    payload.chunk_size = Math.max(1, Math.min(chunkSize, 1000))
  }

  const result = await adminApiFetch('/api/v1/admin/prices/cache-refresh', {
    method: 'POST',
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
  }, { tokenMode: 'service-or-admin' })

  if (result.ok) {
    const batches = (result.payload as any)?.batches ?? 0
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: `Price cache warm queued for ${symbols.length} symbol(s) in ${batches} batch(es).` })
  }

  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function triggerAiCacheRefresh(formData: FormData) {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const rawSymbols = formData.get('ai_symbols')?.toString() ?? ''
  const symbols = rawSymbols
    .split(/[, \n\r\t]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)

  const rawIds = formData.get('analysis_ids')?.toString() ?? ''
  const analysisIds = rawIds
    .split(/[, \n\r\t]+/)
    .map((s) => s.trim())
    .filter(Boolean)

  if (!symbols.length && !analysisIds.length) {
    const result = await adminApiFetch('/api/v1/admin/ai-analysis/refresh', { method: 'POST' }, { tokenMode: 'service-or-admin' })
    if (result.ok) {
      redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: 'AI memo views refreshed and caches invalidated.' })
    }
    redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
  }

  const reason = formData.get('ai_reason')?.toString().trim() || 'admin-ui'
  const includeProximity = formData.get('include_proximity')?.toString() === 'on'
  const chunkRaw = formData.get('ai_chunk_size')?.toString().trim()
  const chunkSize = chunkRaw ? Number.parseInt(chunkRaw, 10) : undefined

  const payload: Record<string, unknown> = {
    symbols,
    analysis_ids: analysisIds,
    reason,
    include_proximity: includeProximity,
  }
  if (chunkSize && Number.isFinite(chunkSize)) {
    payload.chunk_size = Math.max(1, Math.min(chunkSize, 1000))
  }

  const result = await adminApiFetch('/api/v1/admin/ai-analysis/cache-refresh', {
    method: 'POST',
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
  }, { tokenMode: 'service-or-admin' })

  if (result.ok) {
    const symbolCount = (result.payload as any)?.symbols ?? symbols.length
    const idCount = (result.payload as any)?.analysis_ids ?? analysisIds.length
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: `AI cache refresh queued (symbols=${symbolCount}, analyses=${idCount}).` })
  }

  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function triggerAiAnalysisRefresh() {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const result = await adminApiFetch('/api/v1/admin/ai-analysis/refresh', { method: 'POST' }, { tokenMode: 'service-or-admin' })
  if (result.ok) {
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: 'AI memo views refreshed and caches invalidated.' })
  }
  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

async function triggerSentimentEnqueue(formData: FormData) {
  'use server'

  await requireAdminSession(UNAUTHORIZED_REDIRECT, { attemptedPath: '/admin', method: 'POST' })
  const rawSymbol = formData.get('sentiment_symbol')?.toString() ?? ''
  const symbol = rawSymbol.trim().toUpperCase()
  if (!symbol) {
    redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: 'Provide a symbol to enqueue.' })
  }

  const title = formData.get('sentiment_title')?.toString().trim() || undefined
  const url = formData.get('sentiment_url')?.toString().trim() || undefined
  const priorityRaw = formData.get('sentiment_priority')?.toString().trim()
  const priority = priorityRaw ? Number.parseInt(priorityRaw, 10) : 70
  const force = formData.get('sentiment_force')?.toString() === 'on'

  const params = new URLSearchParams()
  params.set('symbol', symbol)
  params.set('priority', Number.isFinite(priority) ? String(priority) : '70')
  params.set('force', force ? 'true' : 'false')
  if (title) {
    params.set('title', title)
  }
  if (url) {
    params.set('url', url)
  }

  const result = await adminApiFetch(`/api/v1/admin/news/queue/enqueue?${params.toString()}`, {
    method: 'POST',
  }, { tokenMode: 'service-or-admin' })

  if (result.ok) {
    redirectWithFlashNotice({ pathname: '/admin', status: 'success', message: `Enqueued ${symbol} for sentiment analysis.` })
  }

  redirectWithFlashNotice({ pathname: '/admin', status: 'error', message: result.message })
}

type SentimentQueueStats = {
  total: number | null
  ready: number | null
  future: number | null
  lastProcessedTs: string | null
  lastProcessedSymbol: string | null
}

async function getPendingSentimentCounts(): Promise<SentimentQueueStats> {
  if (!hasAuthServiceToken()) {
    return { total: null, ready: null, future: null, lastProcessedTs: null, lastProcessedSymbol: null }
  }
  try {
    const result = await adminApiFetch('/api/v1/admin/news/queue?status=pending&limit=1', { method: 'GET' }, { tokenMode: 'service' })
    if (!result.ok || !result.payload) {
      return { total: null, ready: null, future: null, lastProcessedTs: null, lastProcessedSymbol: null }
    }
    const data = result.payload as any
    const total = typeof data.total === 'number' ? data.total : Array.isArray(data.items) ? data.items.length : null
    const ready = typeof data.pending_ready === 'number' ? data.pending_ready : null
    const future = typeof data.pending_future === 'number' ? data.pending_future : null
    const lastProcessed =
      typeof data.last_processed_ts === 'string' || data.last_processed_ts instanceof Date
        ? data.last_processed_ts
        : typeof data.last_started_ts === 'string' || data.last_started_ts instanceof Date
          ? data.last_started_ts
          : typeof data.last_completed_ts === 'string' || data.last_completed_ts instanceof Date
            ? data.last_completed_ts
            : null
    const lastProcessedSymbol =
      typeof data.last_processed_symbol === 'string' && data.last_processed_symbol.trim().length > 0
        ? data.last_processed_symbol.trim().toUpperCase()
        : null
    return { total, ready, future, lastProcessedTs: lastProcessed, lastProcessedSymbol }
  } catch (err) {
    console.warn('Failed to fetch sentiment queue stats', err)
    return { total: null, ready: null, future: null, lastProcessedTs: null, lastProcessedSymbol: null }
  }
}

export default async function AdminPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[]>
}) {
  await requireAdminSession('/', { attemptedPath: '/admin', method: 'GET' })

  const sentimentCounts = await getPendingSentimentCounts()
  const formatCount = (value: number | null) => (typeof value === 'number' ? value.toLocaleString() : '-')
  const formatLastProcessed = (symbol: string | null, ts: string | null) => {
    const formatted = formatEasternDateTime(ts, '-')
    if (!symbol) return formatted
    return `${symbol} • ${formatted}`
  }

  const flashNotice = parseFlashNotice(searchParams)

  return (
    <div className="container space-y-6 py-10">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Admin Tools</h1>
        <p className="mt-1 text-muted-foreground">
          Quick links and operational helpers that are only available to admin users.
        </p>
      </div>

      {flashNotice ? <FlashNotice status={flashNotice.status} message={flashNotice.message} /> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Queue Overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="rounded-md border border-border/60 bg-muted/10 p-3 text-sm text-foreground">
              <div className="mb-2 flex items-baseline justify-between">
                <h2 className="text-sm font-semibold text-foreground">Analysis Queue</h2>
                <span className="text-xs text-muted-foreground">rankalpha.sentiment_analysis_queue</span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-4">
                <div>
                  <span className="block text-xs uppercase text-muted-foreground">Ready now</span>
                  <span className="text-base font-semibold">{formatCount(sentimentCounts.ready)}</span>
                </div>
                <div>
                  <span className="block text-xs uppercase text-muted-foreground">Scheduled later</span>
                  <span className="text-base font-semibold">{formatCount(sentimentCounts.future)}</span>
                </div>
                <div>
                  <span className="block text-xs uppercase text-muted-foreground">Total pending</span>
                  <span className="text-base font-semibold">{formatCount(sentimentCounts.total)}</span>
                </div>
                <div>
                  <span className="block text-xs uppercase text-muted-foreground">Last processed</span>
                  <span className="text-base font-semibold">
                    {formatLastProcessed(sentimentCounts.lastProcessedSymbol, sentimentCounts.lastProcessedTs)}
                  </span>
                </div>
              </div>
            </div>
            <Link
              href="/admin/sentiment-queue"
              className="inline-flex w-fit items-center rounded-md border border-border/60 bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
            >
              View sentiment queue
            </Link>
            <p>
              These endpoints still respect bearer token security. Use the admin role to trigger common
              operational tasks without reaching for cURL.
            </p>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Queue Maintenance</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 lg:grid-cols-2">
            <form action={previewQueueMaintenance} className="space-y-2 rounded-md border border-border/60 bg-background/50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-foreground">Dry run</span>
                  <p className="text-xs text-muted-foreground">POST /api/v1/admin/news/queue/maintain (dry_run=true)</p>
                </div>
                <button type="submit" className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90">Preview</button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 text-xs text-muted-foreground">
                <label className="inline-flex items-center gap-2 text-sm text-foreground">
                  <input name="qm_include_event" type="checkbox" className="h-4 w-4" defaultChecked />
                  Include event-specific duplicates
                </label>
                <label className="block">
                  Cleanup done older than (days)
                  <input name="qm_cleanup_done_days" type="number" min={0} defaultValue={30} className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm" />
                </label>
                <label className="block">
                  Cleanup failed older than (days)
                  <input name="qm_cleanup_failed_days" type="number" min={0} defaultValue={14} className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm" />
                </label>
              </div>
            </form>

            <form action={applyQueueMaintenance} className="space-y-2 rounded-md border border-border/60 bg-background/50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-foreground">Apply cleanup</span>
                  <p className="text-xs text-muted-foreground">POST /api/v1/admin/news/queue/maintain (dry_run=false)</p>
                </div>
                <button type="submit" className="inline-flex items-center rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:opacity-90">Apply</button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 text-xs text-muted-foreground">
                <label className="inline-flex items-center gap-2 text-sm text-foreground">
                  <input name="qm_include_event" type="checkbox" className="h-4 w-4" defaultChecked />
                  Include event-specific duplicates
                </label>
                <label className="block">
                  Cleanup done older than (days)
                  <input name="qm_cleanup_done_days" type="number" min={0} defaultValue={30} className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm" />
                </label>
                <label className="block">
                  Cleanup failed older than (days)
                  <input name="qm_cleanup_failed_days" type="number" min={0} defaultValue={14} className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm" />
                </label>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Grades & Weights</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              action={triggerGradesRefresh}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-background/50 p-3"
            >
              <div>
                <span className="font-medium text-foreground">Refresh grades</span>
                <p className="text-xs text-muted-foreground">POST /api/v1/admin/grades/refresh</p>
              </div>
              <button
                type="submit"
                className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                Trigger
              </button>
            </form>

            <form
              action={triggerPublicGradesRefresh}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-background/50 p-3"
            >
              <div>
                <span className="font-medium text-foreground">Refresh public grading cache</span>
                <p className="text-xs text-muted-foreground">POST /api/v1/grading/refresh</p>
              </div>
              <button
                type="submit"
                className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                Trigger
              </button>
            </form>

            <form
              action={triggerWeightsRecompute}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-background/50 p-3"
            >
              <div>
                <span className="font-medium text-foreground">Force weight recompute</span>
                <p className="text-xs text-muted-foreground">POST /api/v1/admin/weights/recompute</p>
              </div>
              <button
                type="submit"
                className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                Set flag
              </button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Cache Warmers</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <form
              action={triggerPriceCacheRefresh}
              className="space-y-2 rounded-md border border-border/60 bg-background/50 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-foreground">Warm price cache</span>
                  <p className="text-xs text-muted-foreground">POST /api/v1/admin/prices/cache-refresh</p>
                </div>
                <button
                  type="submit"
                  className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
                >
                  Enqueue
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="text-xs text-muted-foreground">
                  Symbols (comma or whitespace separated)
                  <textarea
                    name="symbols"
                    rows={3}
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                    placeholder="AAPL MSFT NVDA"
                    required
                  />
                </label>
                <div className="space-y-2 text-xs text-muted-foreground">
                  <label className="block">
                    Reason
                    <input
                      name="reason"
                      type="text"
                      defaultValue="admin-ui"
                      className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                    />
                  </label>
                  <label className="block">
                    Chunk size (optional)
                    <input
                      name="chunk_size"
                      type="number"
                      min={1}
                      max={1000}
                      className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                      placeholder="50"
                    />
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm text-foreground">
                    <input name="force" type="checkbox" className="h-4 w-4" defaultChecked />
                    Force refresh
                  </label>
                </div>
              </div>
            </form>

            <form
              action={triggerAiCacheRefresh}
              className="space-y-2 rounded-md border border-border/60 bg-background/50 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-foreground">Refresh AI memo cache</span>
                  <p className="text-xs text-muted-foreground">POST /api/v1/admin/ai-analysis/cache-refresh</p>
                  <p className="text-xs text-muted-foreground">Leave both fields empty to refresh all analyses.</p>
                </div>
                <button
                  type="submit"
                  className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
                >
                  Enqueue
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="text-xs text-muted-foreground">
                  Symbols (optional)
                  <textarea
                    name="ai_symbols"
                    rows={3}
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                    placeholder="AAPL MSFT"
                  />
                </label>
                <label className="text-xs text-muted-foreground">
                  Analysis IDs (optional)
                  <textarea
                    name="analysis_ids"
                    rows={3}
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                    placeholder="uuid-1 uuid-2"
                  />
                </label>
              </div>
              <div className="grid gap-2 sm:grid-cols-3 text-xs text-muted-foreground">
                <label className="block">
                  Reason
                  <input
                    name="ai_reason"
                    type="text"
                    defaultValue="admin-ui"
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                  />
                </label>
                <label className="block">
                  Chunk size (optional)
                  <input
                    name="ai_chunk_size"
                    type="number"
                    min={1}
                    max={1000}
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                    placeholder="25"
                  />
                </label>
                <label className="inline-flex items-center gap-2 text-sm text-foreground">
                  <input name="include_proximity" type="checkbox" className="h-4 w-4" />
                  Include proximity warm-up
                </label>
              </div>
            </form>

            <form
              action={triggerAiAnalysisRefresh}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-background/50 p-3"
            >
              <div>
                <span className="font-medium text-foreground">Refresh AI memo views</span>
                <p className="text-xs text-muted-foreground">POST /api/v1/admin/ai-analysis/refresh</p>
              </div>
              <button
                type="submit"
                className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                Refresh
              </button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sentiment Enqueue</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              action={triggerSentimentEnqueue}
              className="space-y-2 rounded-md border border-border/60 bg-background/50 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-foreground">Enqueue sentiment analysis</span>
                  <p className="text-xs text-muted-foreground">POST /api/v1/admin/news/queue/enqueue</p>
                </div>
                <button
                  type="submit"
                  className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
                >
                  Enqueue
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 text-xs text-muted-foreground">
                <label className="block">
                  Symbol
                  <input
                    name="sentiment_symbol"
                    type="text"
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm uppercase"
                    placeholder="AAPL"
                    required
                  />
                </label>
                <label className="block">
                  Priority
                  <input
                    name="sentiment_priority"
                    type="number"
                    defaultValue={70}
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                    min={0}
                    max={100}
                  />
                </label>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 text-xs text-muted-foreground">
                <label className="block">
                  Title (optional)
                  <input
                    name="sentiment_title"
                    type="text"
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                  />
                </label>
                <label className="block">
                  URL (optional)
                  <input
                    name="sentiment_url"
                    type="text"
                    className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                  />
                </label>
              </div>
              <label className="inline-flex items-center gap-2 text-sm text-foreground">
                <input name="sentiment_force" type="checkbox" className="h-4 w-4" defaultChecked />
                Force run (bypass recency guard)
              </label>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Quick Links</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-background/50 p-3">
              <div>
                <span className="font-medium text-foreground">Newswire trace viewer</span>
                <p className="text-xs text-muted-foreground">Inspect collector, dedup, and prefilter decisions before enabling LLM analysis.</p>
              </div>
              <Link
                href="/admin/newswire"
                className="inline-flex items-center rounded-md border border-border/60 px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
              >
                Open viewer
              </Link>
            </div>
            <div className="rounded-md border border-border/60 bg-background/50 p-3 text-xs text-muted-foreground">
              <Link href="/api/v1/auth/users" className="text-primary hover:underline">
                GET /api/v1/auth/users
              </Link>{' '}
              - inspect current user → role assignments.
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardContent className="text-xs text-muted-foreground">
            Looking for something else? Admin endpoints live under <code>/api/v1/admin</code> and{' '}
            <code>/api/v1/ops</code>. Use your browser dev tools or Postman for payload-based calls.
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
