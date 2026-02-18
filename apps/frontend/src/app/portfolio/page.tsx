import { Metadata } from 'next'
import Link from 'next/link'

import { FlashNotice } from '@/components/flash_notice'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DataTable } from '@/components/ui/data-table'
import { ColumnHeaderTooltip } from '@/components/column-header-tooltip'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { formatEasternDate, formatEasternDateTime } from '@/lib/date'
import { adminApiFetch } from '@/lib/server/admin_api'
import { parseFlashNotice, redirectWithFlashNotice } from '@/lib/server/flash_notice'
import { requireAdminSession } from '@/lib/server/require_admin'

export const metadata: Metadata = {
  title: 'Portfolio | RankAlpha',
}

async function createPortfolioAction(formData: FormData) {
  'use server'

  await requireAdminSession('/')

  const portfolioName = formData.get('portfolio_name')?.toString().trim() || ''
  const portfolioKind = formData.get('portfolio_kind')?.toString().trim() || 'MODEL'
  const currencyCode = formData.get('currency_code')?.toString().trim() || 'USD'
  const brokerName = formData.get('broker_name')?.toString().trim() || undefined
  const brokerAccountId = formData.get('broker_account_id')?.toString().trim() || undefined
  const description = formData.get('description')?.toString().trim() || undefined

  const result = await adminApiFetch('/api/v1/portfolio/portfolios', {
    method: 'POST',
    body: JSON.stringify({
      portfolio_name: portfolioName,
      portfolio_kind: portfolioKind,
      currency_code: currencyCode,
      broker_name: brokerName,
      broker_account_id: brokerAccountId,
      description,
    }),
  }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })

  if (result.ok) {
    redirectWithFlashNotice({ pathname: '/portfolio', status: 'success', message: 'Portfolio created.' })
  }
  redirectWithFlashNotice({ pathname: '/portfolio', status: 'error', message: result.message })
}

async function createDeploymentAction(formData: FormData) {
  'use server'

  const session = await requireAdminSession('/')

  const brokerPortfolioId = formData.get('broker_portfolio_id')?.toString().trim() || ''
  const modelPortfolioId = formData.get('model_portfolio_id')?.toString().trim() || ''
  const allocationPct = formData.get('allocation_pct')?.toString().trim() || '0'
  const effectiveFrom = formData.get('effective_from')?.toString().trim() || undefined

  const result = await adminApiFetch('/api/v1/portfolio/deployments', {
    method: 'POST',
    body: JSON.stringify({
      broker_portfolio_id: brokerPortfolioId,
      model_portfolio_id: modelPortfolioId,
      allocation_pct: allocationPct,
      effective_from: effectiveFrom || undefined,
      created_by: session.user?.email || undefined,
    }),
  }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })

  if (result.ok) {
    redirectWithFlashNotice({
      pathname: '/portfolio',
      status: 'success',
      message: 'Deployment saved.',
      extraParams: { portfolio_id: brokerPortfolioId },
    })
  }
  redirectWithFlashNotice({
    pathname: '/portfolio',
    status: 'error',
    message: result.message,
    extraParams: { portfolio_id: brokerPortfolioId },
  })
}

async function createRunAction(formData: FormData) {
  'use server'

  const session = await requireAdminSession('/')

  const portfolioId = formData.get('portfolio_id')?.toString().trim() || ''
  const runKind = formData.get('run_kind')?.toString().trim() || 'MODEL_CONSTRUCTION'
  const asOfDate = formData.get('as_of_date')?.toString().trim() || formatEasternDate(Date.now())

  const result = await adminApiFetch('/api/v1/portfolio/runs', {
    method: 'POST',
    body: JSON.stringify({
      portfolio_id: portfolioId,
      run_kind: runKind,
      as_of_date: asOfDate,
      created_by: session.user?.email || undefined,
    }),
  }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })

  if (result.ok) {
    const payload = (result.payload ?? {}) as any
    const runId = payload.run_id as string | undefined
    const msg = `Run created${typeof payload.run_seq === 'number' ? ` (seq ${payload.run_seq}).` : '.'}`
    redirectWithFlashNotice({
      pathname: '/portfolio',
      status: 'success',
      message: msg,
      extraParams: { portfolio_id: portfolioId, run_id: runId ?? null },
    })
  }
  redirectWithFlashNotice({
    pathname: '/portfolio',
    status: 'error',
    message: result.message,
    extraParams: { portfolio_id: portfolioId },
  })
}

async function upsertOrdersAction(formData: FormData) {
  'use server'

  await requireAdminSession('/')

  const portfolioId = formData.get('portfolio_id')?.toString().trim() || ''
  const runId = formData.get('run_id')?.toString().trim() || ''
  const rawOrders = formData.get('orders_json')?.toString().trim() || ''

  let orders: unknown
  try {
    orders = rawOrders ? JSON.parse(rawOrders) : []
  } catch {
    redirectWithFlashNotice({
      pathname: '/portfolio',
      status: 'error',
      message: 'Invalid JSON in orders.',
      extraParams: { portfolio_id: portfolioId, run_id: runId },
    })
  }

  if (!Array.isArray(orders)) {
    redirectWithFlashNotice({
      pathname: '/portfolio',
      status: 'error',
      message: 'orders_json must be a JSON array.',
      extraParams: { portfolio_id: portfolioId, run_id: runId },
    })
  }

  const result = await adminApiFetch(`/api/v1/portfolio/runs/${runId}/orders`, {
    method: 'POST',
    body: JSON.stringify({ orders }),
  }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })

  if (result.ok) {
    const payload = (result.payload ?? {}) as any
    const count = Array.isArray(payload.order_ids) ? payload.order_ids.length : 0
    redirectWithFlashNotice({
      pathname: '/portfolio',
      status: 'success',
      message: `Saved ${count} order line(s).`,
      extraParams: { portfolio_id: portfolioId, run_id: runId },
    })
  }
  redirectWithFlashNotice({
    pathname: '/portfolio',
    status: 'error',
    message: result.message,
    extraParams: { portfolio_id: portfolioId, run_id: runId },
  })
}

async function setOrderApprovalAction(formData: FormData) {
  'use server'

  const session = await requireAdminSession('/')

  const portfolioId = formData.get('portfolio_id')?.toString().trim() || ''
  const runId = formData.get('run_id')?.toString().trim() || ''
  const orderId = formData.get('order_id')?.toString().trim() || ''
  const decision = formData.get('decision')?.toString().trim().toUpperCase() || 'APPROVE'

  const endpoint = decision === 'REJECT' ? 'reject' : 'approve'
  const result = await adminApiFetch(`/api/v1/portfolio/orders/${orderId}/${endpoint}`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: session.user?.email || undefined }),
  }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })

  if (result.ok) {
    redirectWithFlashNotice({
      pathname: '/portfolio',
      status: 'success',
      message: `Order ${endpoint}d.`,
      extraParams: { portfolio_id: portfolioId, run_id: runId },
    })
  }
  redirectWithFlashNotice({
    pathname: '/portfolio',
    status: 'error',
    message: result.message,
    extraParams: { portfolio_id: portfolioId, run_id: runId },
  })
}

async function approveRunAction(formData: FormData) {
  'use server'

  const session = await requireAdminSession('/')

  const portfolioId = formData.get('portfolio_id')?.toString().trim() || ''
  const runId = formData.get('run_id')?.toString().trim() || ''

  const result = await adminApiFetch(`/api/v1/portfolio/runs/${runId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: session.user?.email || undefined }),
  }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })

  if (result.ok) {
    redirectWithFlashNotice({
      pathname: '/portfolio',
      status: 'success',
      message: 'Run approved.',
      extraParams: { portfolio_id: portfolioId, run_id: runId },
    })
  }
  redirectWithFlashNotice({
    pathname: '/portfolio',
    status: 'error',
    message: result.message,
    extraParams: { portfolio_id: portfolioId, run_id: runId },
  })
}

function badgeTone(value: string): BadgeProps['variant'] {
  const key = value.toUpperCase()
  if (key === 'APPROVED') return 'success'
  if (key === 'REJECTED') return 'danger'
  if (key === 'SUPERSEDED') return 'info'
  if (key === 'IN_REVIEW') return 'warning'
  if (key === 'DRAFT' || key === 'PENDING') return 'info'
  return 'secondary'
}

export default async function PortfolioPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[]>
}) {
  await requireAdminSession('/')

  const flashNotice = parseFlashNotice(searchParams)

  const selectedPortfolioId = typeof searchParams?.portfolio_id === 'string' ? searchParams.portfolio_id : undefined
  const selectedRunId = typeof searchParams?.run_id === 'string' ? searchParams.run_id : undefined
  const recSymbol = typeof searchParams?.rec_symbol === 'string' ? searchParams.rec_symbol : undefined

  const portfoliosResult = await adminApiFetch('/api/v1/portfolio/portfolios', { method: 'GET' }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })
  const portfolios: any[] = portfoliosResult.ok && Array.isArray(portfoliosResult.payload) ? portfoliosResult.payload : []

  const selectedPortfolio = selectedPortfolioId
    ? portfolios.find((p) => p?.portfolio_id === selectedPortfolioId)
    : undefined

  const selectedKind = (selectedPortfolio?.portfolio_kind as string | undefined) || ''
  const isBrokerSelected = selectedKind.toUpperCase() === 'BROKER'

  const deploymentsResult =
    isBrokerSelected && selectedPortfolioId
      ? await adminApiFetch(`/api/v1/portfolio/deployments?broker_portfolio_id=${encodeURIComponent(selectedPortfolioId)}`, { method: 'GET' }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })
      : { ok: true, payload: [] as any[] }

  const deployments: any[] = deploymentsResult.ok && Array.isArray(deploymentsResult.payload) ? deploymentsResult.payload : []

  const runsResult =
    selectedPortfolioId
      ? await adminApiFetch(`/api/v1/portfolio/runs?portfolio_id=${encodeURIComponent(selectedPortfolioId)}&limit=200`, { method: 'GET' }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })
      : { ok: true, payload: [] as any[] }

  const runs: any[] = runsResult.ok && Array.isArray(runsResult.payload) ? runsResult.payload : []

  const ordersResult =
    selectedRunId
      ? await adminApiFetch(`/api/v1/portfolio/runs/${encodeURIComponent(selectedRunId)}/orders`, { method: 'GET' }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })
      : { ok: true, payload: [] as any[] }
  const orders: any[] = ordersResult.ok && Array.isArray(ordersResult.payload) ? ordersResult.payload : []

  const recParams = new URLSearchParams({ limit: '50', is_live: 'false' })
  if (recSymbol) recParams.set('symbol', recSymbol)
  const tradeRecsResult = await adminApiFetch(`/api/v1/portfolio/trade-recommendations?${recParams.toString()}`, { method: 'GET' }, { tokenMode: 'service', missingTokenMessage: 'AUTH_SERVICE_TOKEN not configured' })
  const tradeRecs: any[] = tradeRecsResult.ok && Array.isArray(tradeRecsResult.payload) ? tradeRecsResult.payload : []

  const brokerPortfolios = portfolios.filter((p) => (p?.portfolio_kind || '').toUpperCase() === 'BROKER')
  const modelPortfolios = portfolios.filter((p) => (p?.portfolio_kind || '').toUpperCase() === 'MODEL')
  const sleevePortfolios = portfolios.filter((p) => (p?.portfolio_kind || '').toUpperCase() === 'SLEEVE')

  const defaultRunKind = (() => {
    const key = (selectedKind || '').toUpperCase()
    if (key === 'BROKER') return 'BROKER_REBALANCE'
    if (key === 'SLEEVE') return 'SLEEVE_BUILD'
    return 'MODEL_CONSTRUCTION'
  })()

  const todayIso = formatEasternDate(Date.now())

  const approvedOrderCount = orders.filter((o) => (o?.approval_status || '').toUpperCase() === 'APPROVED').length
  const canApproveRun = Boolean(selectedRunId && orders.length > 0 && approvedOrderCount === orders.length)

  return (
    <div className="container space-y-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Portfolio</h1>
          <p className="mt-1 text-muted-foreground">
            Deploy model portfolios into broker accounts, review daily rebalance runs, and approve order lines.
          </p>
        </div>
        <div className="rounded-xl border border-border/60 bg-background/70 px-4 py-2 text-xs text-muted-foreground">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span>
              <span className="font-semibold text-foreground">{brokerPortfolios.length}</span> broker
            </span>
            <span>
              <span className="font-semibold text-foreground">{modelPortfolios.length}</span> model
            </span>
            <span>
              <span className="font-semibold text-foreground">{sleevePortfolios.length}</span> sleeve
            </span>
          </div>
        </div>
      </div>

      {flashNotice ? <FlashNotice status={flashNotice.status} message={flashNotice.message} /> : null}

      {!portfoliosResult.ok ? (
        <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
          {portfoliosResult.message}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-4">
          <Card>
            <CardHeader>
              <CardTitle>Portfolios</CardTitle>
              <CardDescription>Broker accounts, model books, and sleeves</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Broker</div>
                <div className="space-y-1">
                  {brokerPortfolios.length ? brokerPortfolios.map((p) => (
                    <Link
                      key={p.portfolio_id}
                      href={`/portfolio?portfolio_id=${encodeURIComponent(p.portfolio_id)}`}
                      className={
                        p.portfolio_id === selectedPortfolioId
                          ? 'block rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-foreground'
                          : 'block rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-muted-foreground hover:border-primary/30 hover:bg-background/80 hover:text-foreground'
                      }
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-foreground">{p.portfolio_name}</span>
                        <span className="text-[11px] text-muted-foreground">{p.currency_code}</span>
                      </div>
                      {(p.broker_name || p.broker_account_id) && (
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          {(p.broker_name || 'BROKER').toString()} · {(p.broker_account_id || '').toString()}
                        </div>
                      )}
                    </Link>
                  )) : (
                    <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-muted-foreground">No broker portfolios yet.</div>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Model</div>
                <div className="space-y-1">
                  {modelPortfolios.length ? modelPortfolios.map((p) => (
                    <Link
                      key={p.portfolio_id}
                      href={`/portfolio?portfolio_id=${encodeURIComponent(p.portfolio_id)}`}
                      className={
                        p.portfolio_id === selectedPortfolioId
                          ? 'block rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-foreground'
                          : 'block rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-muted-foreground hover:border-primary/30 hover:bg-background/80 hover:text-foreground'
                      }
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-foreground">{p.portfolio_name}</span>
                        <span className="text-[11px] text-muted-foreground">{p.currency_code}</span>
                      </div>
                      {p.description && (
                        <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{p.description}</div>
                      )}
                    </Link>
                  )) : (
                    <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-muted-foreground">No model portfolios yet.</div>
                  )}
                </div>
              </div>

              {sleevePortfolios.length ? (
                <details className="rounded-lg border border-border/60 bg-background/50 p-3">
                  <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Sleeves ({sleevePortfolios.length})
                  </summary>
                  <div className="mt-2 space-y-1">
                    {sleevePortfolios.slice(0, 30).map((p) => (
                      <Link
                        key={p.portfolio_id}
                        href={`/portfolio?portfolio_id=${encodeURIComponent(p.portfolio_id)}`}
                        className={
                          p.portfolio_id === selectedPortfolioId
                            ? 'block rounded-md border border-primary/40 bg-primary/10 px-2 py-1.5 text-[12px] text-foreground'
                            : 'block rounded-md border border-border/60 bg-background/50 px-2 py-1.5 text-[12px] text-muted-foreground hover:border-primary/30 hover:bg-background/80 hover:text-foreground'
                        }
                      >
                        <span className="font-mono">{p.portfolio_name}</span>
                      </Link>
                    ))}
                  </div>
                </details>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Create Portfolio</CardTitle>
              <CardDescription>Register a broker account or model book</CardDescription>
            </CardHeader>
            <CardContent>
              <form action={createPortfolioAction} className="grid gap-3 text-sm">
                <label className="grid gap-1">
                  <span className="text-xs font-medium text-muted-foreground">Name</span>
                  <input
                    name="portfolio_name"
                    required
                    maxLength={50}
                    className="h-9 rounded-md border border-border/60 bg-background/60 px-3 outline-none focus:border-primary/50"
                    placeholder="e.g., IBKR-U1234567 or Model-Core"
                  />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="grid gap-1">
                    <span className="text-xs font-medium text-muted-foreground">Kind</span>
                    <select
                      name="portfolio_kind"
                      className="h-9 rounded-md border border-border/60 bg-background/60 px-3 outline-none focus:border-primary/50"
                      defaultValue="MODEL"
                    >
                      <option value="MODEL">MODEL</option>
                      <option value="BROKER">BROKER</option>
                      <option value="SLEEVE">SLEEVE</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-xs font-medium text-muted-foreground">Base CCY</span>
                    <input
                      name="currency_code"
                      maxLength={3}
                      defaultValue="USD"
                      className="h-9 rounded-md border border-border/60 bg-background/60 px-3 font-mono uppercase outline-none focus:border-primary/50"
                      placeholder="USD"
                    />
                  </label>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <label className="grid gap-1">
                    <span className="text-xs font-medium text-muted-foreground">Broker</span>
                    <input
                      name="broker_name"
                      maxLength={32}
                      className="h-9 rounded-md border border-border/60 bg-background/60 px-3 outline-none focus:border-primary/50"
                      placeholder="IBKR"
                    />
                  </label>
                  <label className="grid gap-1">
                    <span className="text-xs font-medium text-muted-foreground">Broker Account</span>
                    <input
                      name="broker_account_id"
                      maxLength={64}
                      className="h-9 rounded-md border border-border/60 bg-background/60 px-3 outline-none focus:border-primary/50"
                      placeholder="U1234567"
                    />
                  </label>
                </div>
                <label className="grid gap-1">
                  <span className="text-xs font-medium text-muted-foreground">Description</span>
                  <input
                    name="description"
                    className="h-9 rounded-md border border-border/60 bg-background/60 px-3 outline-none focus:border-primary/50"
                    placeholder="Optional"
                  />
                </label>
                <button
                  type="submit"
                  className="inline-flex items-center justify-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
                >
                  Create
                </button>
              </form>
            </CardContent>
          </Card>

          {isBrokerSelected && selectedPortfolioId ? (
            <Card>
              <CardHeader>
                <CardTitle>Deployments</CardTitle>
                <CardDescription>Model allocations into this broker account</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="overflow-x-auto rounded-lg border border-border/60">
                    <DataTable className="min-w-full text-left text-xs">
                      <thead className="bg-muted/30 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Model" tooltipKey="table.model" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Sleeve" tooltipKey="table.sleeve" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Alloc" tooltipKey="table.alloc" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Active" tooltipKey="table.active" />
                          </th>
                        </tr>
                      </thead>
                    <tbody className="divide-y divide-border/60">
                      {deployments.length ? deployments.map((d) => (
                        <tr key={d.deployment_id} className="bg-background/40">
                          <td className="px-3 py-2">{d.model_portfolio_name}</td>
                          <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">{d.sleeve_portfolio_name}</td>
                          <td className="px-3 py-2">{Number(d.allocation_pct).toFixed(2)}%</td>
                          <td className="px-3 py-2">
                            <Badge variant={d.is_active ? 'success' : 'secondary'} className="px-2 py-0.5 text-[11px]">
                              {d.is_active ? 'ACTIVE' : 'INACTIVE'}
                            </Badge>
                          </td>
                        </tr>
                      )) : (
                        <tr>
                          <td className="px-3 py-3 text-muted-foreground" colSpan={4}>
                            No deployments configured.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </DataTable>
                </div>

                <form action={createDeploymentAction} className="grid gap-3 rounded-lg border border-border/60 bg-background/50 p-3">
                  <input type="hidden" name="broker_portfolio_id" value={selectedPortfolioId} />
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1">
                      <span className="text-xs font-medium text-muted-foreground">Model Portfolio</span>
                      <select
                        name="model_portfolio_id"
                        className="h-9 rounded-md border border-border/60 bg-background/60 px-3 outline-none focus:border-primary/50"
                        required
                        defaultValue=""
                      >
                        <option value="" disabled>Select…</option>
                        {modelPortfolios.map((p) => (
                          <option key={p.portfolio_id} value={p.portfolio_id}>
                            {p.portfolio_name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="grid gap-1">
                      <span className="text-xs font-medium text-muted-foreground">Allocation %</span>
                      <input
                        name="allocation_pct"
                        required
                        defaultValue="0"
                        className="h-9 rounded-md border border-border/60 bg-background/60 px-3 font-mono outline-none focus:border-primary/50"
                        placeholder="e.g., 35"
                      />
                    </label>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1">
                      <span className="text-xs font-medium text-muted-foreground">Effective From</span>
                      <input
                        name="effective_from"
                        type="date"
                        defaultValue={todayIso}
                        className="h-9 rounded-md border border-border/60 bg-background/60 px-3 font-mono outline-none focus:border-primary/50"
                      />
                    </label>
                    <div className="flex items-end">
                      <button
                        type="submit"
                        className="inline-flex w-full items-center justify-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
                      >
                        Save Deployment
                      </button>
                    </div>
                  </div>
                </form>
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="space-y-6 lg:col-span-4">
          <Card>
            <CardHeader>
              <CardTitle>Runs</CardTitle>
              <CardDescription>Daily portfolio construction drafts and approvals</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {!selectedPortfolioId ? (
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3 text-muted-foreground">
                  Select a portfolio to view runs.
                </div>
              ) : (
                <>
                  <div className="overflow-x-auto rounded-lg border border-border/60">
                    <DataTable className="min-w-full text-left text-xs">
                      <thead className="bg-muted/30 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="As of" tooltipKey="table.date" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Kind" tooltipKey="table.kind" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Seq" tooltipKey="table.seq" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Status" tooltipKey="table.status" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Orders" tooltipKey="table.orders" />
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/60">
                        {runs.length ? runs.slice(0, 60).map((r) => {
                          const isActive = r.run_id === selectedRunId
                          return (
                            <tr key={r.run_id} className={isActive ? 'bg-primary/10' : 'bg-background/40'}>
                              <td className="px-3 py-2">
                                <Link
                                  href={`/portfolio?portfolio_id=${encodeURIComponent(selectedPortfolioId)}&run_id=${encodeURIComponent(r.run_id)}`}
                                  className="font-mono text-[11px] text-foreground hover:underline"
                                >
                                  {r.as_of_date}
                                </Link>
                              </td>
                              <td className="px-3 py-2 text-[11px] text-muted-foreground">{r.run_kind}</td>
                              <td className="px-3 py-2 font-mono">{r.run_seq}</td>
                              <td className="px-3 py-2">
                                <Badge variant={badgeTone(r.status)} className="px-2 py-0.5 text-[11px]">
                                  {r.status}
                                </Badge>
                              </td>
                              <td className="px-3 py-2 font-mono">
                                {r.approved_order_count}/{r.order_count}
                              </td>
                            </tr>
                          )
                        }) : (
                          <tr>
                            <td className="px-3 py-3 text-muted-foreground" colSpan={5}>
                              No runs yet.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </DataTable>
                  </div>

                  <form action={createRunAction} className="grid gap-3 rounded-lg border border-border/60 bg-background/50 p-3">
                    <input type="hidden" name="portfolio_id" value={selectedPortfolioId} />
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="grid gap-1">
                        <span className="text-xs font-medium text-muted-foreground">Run Kind</span>
                        <select
                          name="run_kind"
                          className="h-9 rounded-md border border-border/60 bg-background/60 px-3 outline-none focus:border-primary/50"
                          defaultValue={defaultRunKind}
                        >
                          <option value="MODEL_CONSTRUCTION">MODEL_CONSTRUCTION</option>
                          <option value="BROKER_REBALANCE">BROKER_REBALANCE</option>
                          <option value="SLEEVE_BUILD">SLEEVE_BUILD</option>
                        </select>
                      </label>
                      <label className="grid gap-1">
                        <span className="text-xs font-medium text-muted-foreground">As Of</span>
                        <input
                          name="as_of_date"
                          type="date"
                          defaultValue={todayIso}
                          className="h-9 rounded-md border border-border/60 bg-background/60 px-3 font-mono outline-none focus:border-primary/50"
                        />
                      </label>
                    </div>
                    <button
                      type="submit"
                      className="inline-flex items-center justify-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
                    >
                      Create Run
                    </button>
                  </form>

                  {selectedRunId ? (
                    <div className="rounded-lg border border-border/60 bg-muted/10 p-3 text-xs text-muted-foreground">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-semibold text-foreground">Selected run</span>
                        <span className="font-mono text-[11px]">{selectedRunId}</span>
                      </div>
                      <div className="mt-2 grid gap-1">
                        <div>Created: {formatEasternDateTime(runs.find((r) => r.run_id === selectedRunId)?.created_at)}</div>
                        <div>Approved: {formatEasternDateTime(runs.find((r) => r.run_id === selectedRunId)?.approved_at)}</div>
                      </div>
                    </div>
                  ) : null}
                </>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6 lg:col-span-4">
          <Card>
            <CardHeader>
              <CardTitle>Orders</CardTitle>
              <CardDescription>Per-line approvals; run approves when all lines approved</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {!selectedRunId ? (
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3 text-muted-foreground">
                  Select a run to review orders.
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 bg-background/50 p-3">
                    <div className="text-xs text-muted-foreground">
                      Approved <span className="font-mono text-foreground">{approvedOrderCount}/{orders.length}</span>
                    </div>
                    <form action={approveRunAction}>
                      <input type="hidden" name="portfolio_id" value={selectedPortfolioId} />
                      <input type="hidden" name="run_id" value={selectedRunId} />
                      <button
                        type="submit"
                        disabled={!canApproveRun}
                        className="inline-flex items-center rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                        title={canApproveRun ? 'Approve run' : 'Approve all order lines first'}
                      >
                        Approve Run
                      </button>
                    </form>
                  </div>

                  <div className="overflow-x-auto rounded-lg border border-border/60">
                    <DataTable className="min-w-full text-left text-xs">
                      <thead className="bg-muted/30 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Line" tooltipKey="table.seq" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Symbol" tooltipKey="table.symbol" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Action" tooltipKey="table.action" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Qty" tooltipKey="table.qty" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Type" tooltipKey="table.type" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Status" tooltipKey="table.status" />
                          </th>
                          <th className="px-3 py-2 font-semibold">
                            <ColumnHeaderTooltip label="Review" tooltipKey="table.details" />
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/60">
                        {orders.length ? orders.map((o) => (
                          <tr key={o.order_id} className="bg-background/40">
                            <td className="px-3 py-2 font-mono">{o.line_no}</td>
                            <td className="px-3 py-2 font-medium text-foreground">{o.symbol}</td>
                            <td className="px-3 py-2 font-mono">{o.action}</td>
                            <td className="px-3 py-2 font-mono">{Number(o.qty_shares).toLocaleString()}</td>
                            <td className="px-3 py-2 text-[11px] text-muted-foreground">
                              {(o.order_type || 'MARKET').toString()} · {(o.time_in_force || 'DAY').toString()}
                            </td>
                            <td className="px-3 py-2">
                              <Badge variant={badgeTone(o.approval_status)} className="px-2 py-0.5 text-[11px]">
                                {o.approval_status}
                              </Badge>
                            </td>
                            <td className="px-3 py-2">
                              <div className="flex flex-wrap gap-2">
                                <form action={setOrderApprovalAction}>
                                  <input type="hidden" name="portfolio_id" value={selectedPortfolioId} />
                                  <input type="hidden" name="run_id" value={selectedRunId} />
                                  <input type="hidden" name="order_id" value={o.order_id} />
                                  <input type="hidden" name="decision" value="APPROVE" />
                                  <button
                                    type="submit"
                                    className="rounded-md bg-emerald-600 px-2 py-1 text-[11px] font-medium text-white hover:opacity-90"
                                  >
                                    Approve
                                  </button>
                                </form>
                                <form action={setOrderApprovalAction}>
                                  <input type="hidden" name="portfolio_id" value={selectedPortfolioId} />
                                  <input type="hidden" name="run_id" value={selectedRunId} />
                                  <input type="hidden" name="order_id" value={o.order_id} />
                                  <input type="hidden" name="decision" value="REJECT" />
                                  <button
                                    type="submit"
                                    className="rounded-md bg-rose-600 px-2 py-1 text-[11px] font-medium text-white hover:opacity-90"
                                  >
                                    Reject
                                  </button>
                                </form>
                              </div>
                            </td>
                          </tr>
                        )) : (
                          <tr>
                            <td className="px-3 py-3 text-muted-foreground" colSpan={7}>
                              No order intents for this run.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </DataTable>
                  </div>

                  <details className="rounded-lg border border-border/60 bg-background/50 p-3">
                    <summary className="cursor-pointer text-sm font-medium text-foreground">Upsert order lines (JSON)</summary>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Paste a JSON array of order intent objects. Updates reset approvals to PENDING.
                    </p>
                    <form action={upsertOrdersAction} className="mt-3 grid gap-3">
                      <input type="hidden" name="portfolio_id" value={selectedPortfolioId} />
                      <input type="hidden" name="run_id" value={selectedRunId} />
                      <textarea
                        name="orders_json"
                        rows={8}
                        className="w-full rounded-md border border-border/60 bg-background/60 p-3 font-mono text-[12px] outline-none focus:border-primary/50"
                        placeholder='[{"line_no":1,"symbol":"AAPL","action":"BUY","qty_shares":10,"order_type":"MARKET","time_in_force":"DAY"}]'
                      />
                      <button
                        type="submit"
                        className="inline-flex items-center justify-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
                      >
                        Save Orders
                      </button>
                    </form>
                  </details>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Trade Recommendations</CardTitle>
              <CardDescription>Open ideas (is_live=false) feeding portfolio construction</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <form method="GET" className="flex flex-wrap gap-2">
                {selectedPortfolioId ? <input type="hidden" name="portfolio_id" value={selectedPortfolioId} /> : null}
                {selectedRunId ? <input type="hidden" name="run_id" value={selectedRunId} /> : null}
                <input
                  name="rec_symbol"
                  defaultValue={recSymbol}
                  className="h-9 w-40 rounded-md border border-border/60 bg-background/60 px-3 font-mono text-xs uppercase outline-none focus:border-primary/50"
                  placeholder="Symbol"
                />
                <button
                  type="submit"
                  className="inline-flex items-center rounded-md border border-border/60 bg-background/60 px-3 py-2 text-xs font-medium text-foreground hover:bg-background/80"
                >
                  Filter
                </button>
                {recSymbol ? (
                  <Link
                    href={selectedPortfolioId ? `/portfolio?portfolio_id=${encodeURIComponent(selectedPortfolioId)}${selectedRunId ? `&run_id=${encodeURIComponent(selectedRunId)}` : ''}` : '/portfolio'}
                    className="inline-flex items-center rounded-md border border-border/60 bg-background/60 px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-background/80 hover:text-foreground"
                  >
                    Clear
                  </Link>
                ) : null}
              </form>

              <div className="overflow-x-auto rounded-lg border border-border/60">
                <DataTable className="min-w-full text-left text-xs">
                  <thead className="bg-muted/30 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-semibold">
                        <ColumnHeaderTooltip label="Date" tooltipKey="table.date" />
                      </th>
                      <th className="px-3 py-2 font-semibold">
                        <ColumnHeaderTooltip label="Symbol" tooltipKey="table.symbol" />
                      </th>
                      <th className="px-3 py-2 font-semibold">
                        <ColumnHeaderTooltip label="Action" tooltipKey="table.action" />
                      </th>
                      <th className="px-3 py-2 font-semibold">
                        <ColumnHeaderTooltip label="Price" tooltipKey="table.price" />
                      </th>
                      <th className="px-3 py-2 font-semibold">
                        <ColumnHeaderTooltip label="Source" tooltipKey="table.source" />
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {tradeRecs.length ? tradeRecs.map((r) => (
                      <tr key={r.recommendation_id} className="bg-background/40">
                        <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">{r.recommendation_date}</td>
                        <td className="px-3 py-2 font-medium text-foreground">{r.symbol}</td>
                        <td className="px-3 py-2 font-mono">{r.action}</td>
                        <td className="px-3 py-2 font-mono">
                          {typeof r.recommended_price === 'number' ? r.recommended_price.toFixed(2) : '-'}
                        </td>
                        <td className="px-3 py-2 text-[11px] text-muted-foreground">{r.source_name}</td>
                      </tr>
                    )) : (
                      <tr>
                        <td className="px-3 py-3 text-muted-foreground" colSpan={5}>
                          No open recommendations found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </DataTable>
              </div>

              <div className="rounded-lg border border-border/60 bg-muted/10 p-3 text-xs text-muted-foreground">
                Tip: load recommendations via <span className="font-mono">POST /api/v1/trading/signals</span> (Bearer token), then approve generated runs here.
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
