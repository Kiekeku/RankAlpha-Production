'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftIcon, ArrowUpIcon, ArrowDownIcon } from 'lucide-react'
import { api, SetupHit, SetupSummaryItem } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge, badgeVariants, type BadgeProps } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { formatEasternDate } from '@/lib/date'
import { FIVE_MIN_MS } from '@/lib/time'
import { RecentTickerTracker } from '@/components/recent-ticker-tracker'

const WINDOW_DAYS = 3

export function ScreenerSymbolView({
  symbol,
  focusSlug,
  origin,
  originTab,
}: {
  symbol: string
  focusSlug?: string
  origin?: string
  originTab?: string
}) {
  const { data: setupView, isLoading: setupsLoading, isError: setupsError } = useQuery({
    queryKey: ['setup-symbol-view', symbol, focusSlug || ''],
    queryFn: () => api.getSetupSymbolView({ symbol, window_days: WINDOW_DAYS, focus_slug: focusSlug }),
  })

  const { data: assetDetail } = useQuery({
    queryKey: ['asset-detail', symbol, 'screener-symbol'],
    queryFn: () => api.getAssetDetail(symbol),
    staleTime: FIVE_MIN_MS,
  })

  const summary = setupView?.summary
  const days = useMemo(() => setupView?.days ?? [], [setupView?.days])

  const grouped = useMemo(() => {
    const out: Record<string, { bullish: SetupHit[]; bearish: SetupHit[] }> = {}
    days.forEach((day) => {
      const key = formatEasternDate(day.as_of_date)
      const bull: SetupHit[] = []
      const bear: SetupHit[] = []
      day.hits.forEach((hit) => {
        ;(hit.bias === 'bearish' ? bear : bull).push(hit)
      })
      out[key] = { bullish: bull, bearish: bear }
    })
    return out
  }, [days])

  const focusLabel = useMemo(() => {
    if (!focusSlug) return null
    const match = (summary?.bullish || []).concat(summary?.bearish || []).find((c) => c.slug === focusSlug)
    return match?.label || focusSlug
  }, [focusSlug, summary])

  const fromTicker = origin === 'ticker'
  const backAnchor = originTab === 'setups' ? '#setups-hits' : ''
  const backHref = `/ticker/${encodeURIComponent(symbol)}${originTab ? `?tab=${encodeURIComponent(originTab)}` : ''}${backAnchor}`

  return (
    <div className="space-y-6">
      <RecentTickerTracker symbol={symbol} companyName={assetDetail?.company_name} />
      <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            {fromTicker ? (
              <>
                <Link href="/screener" className="hover:text-foreground">Screener</Link>
                <span className="text-muted-foreground">›</span>
                <span className="text-muted-foreground">Setups</span>
                <span className="text-muted-foreground">›</span>
                <span className="text-xs font-semibold text-foreground">{symbol}</span>
              </>
            ) : (
              <>
                <Link href="/rankings" className="inline-flex items-center gap-1 hover:text-foreground">
                  <ArrowLeftIcon className="h-4 w-4" />
                  Back to Rankings
                </Link>
                <span className="text-muted-foreground">/</span>
                <Link href="/screener" className="hover:text-foreground">Screener</Link>
                <span className="text-muted-foreground">·</span>
                <Link href="/screener" className="text-xs font-semibold text-muted-foreground hover:text-foreground">
                  Full screener
                </Link>
              </>
            )}
          </div>
          <h1 className="text-2xl font-bold tracking-tight">
            {symbol}
            {assetDetail?.company_name ? <span className="ml-2 text-base font-semibold text-muted-foreground">{assetDetail.company_name}</span> : null}
          </h1>
          {focusLabel ? (
            <p className="text-sm text-muted-foreground">
              Focus: <span className="font-semibold text-foreground">{focusLabel}</span>{' '}
              <Link href={`/screener?symbol=${encodeURIComponent(symbol)}`} className="text-primary hover:underline">
                Clear
              </Link>
            </p>
          ) : null}
        </div>
        {fromTicker ? (
          <Link
            href={backHref}
            className="inline-flex items-center justify-center rounded-full border border-outline/12 bg-card px-4 py-2 text-xs font-semibold text-muted-foreground transition hover:border-outline/20 hover:text-foreground"
          >
            Back to {symbol} Setups
          </Link>
        ) : null}
      </section>

      <Card className="border-border/60">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Setup Summary</CardTitle>
          </div>
          {summary ? (
            <NetPill summary={summary} />
          ) : null}
        </CardHeader>
        <CardContent>
          {setupsLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : setupsError ? (
            <p className="text-sm text-destructive">Failed to load setup hits.</p>
          ) : summary ? (
            <div className="space-y-2 text-sm">
              <SetupRow title="Bullish" symbol={symbol} chips={summary.bullish} extra={summary.bullish_extra_count} />
              <SetupRow title="Bearish" symbol={symbol} chips={summary.bearish} extra={summary.bearish_extra_count} />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No setup hits summary available.</p>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/60">
        <CardHeader>
          <CardTitle>Exact Screeners (Last {WINDOW_DAYS} Trading Days)</CardTitle>
        </CardHeader>
        <CardContent>
          {setupsLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : days.length === 0 ? (
            <p className="text-sm text-muted-foreground">No screener hits found for this window.</p>
          ) : (
            <div className="space-y-6">
              {Object.entries(grouped).map(([dateKey, bySide]) => (
                <div key={dateKey} className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-outline/10 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground">
                      {dateKey}
                    </span>
                    {bySide.bullish.length ? (
                      <Badge variant="success">
                        Bullish {bySide.bullish.length}
                      </Badge>
                    ) : null}
                    {bySide.bearish.length ? (
                      <Badge variant="danger">
                        Bearish {bySide.bearish.length}
                      </Badge>
                    ) : null}
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <HitsColumn title="Bullish" hits={bySide.bullish} />
                    <HitsColumn title="Bearish" hits={bySide.bearish} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

    </div>
  )
}

function NetPill({ summary }: { summary: SetupSummaryItem }) {
  if (summary.net_bias === 'neutral') return null
  const label = summary.net_bias === 'bearish' ? 'Net Bearish' : 'Net Bullish'
  const tone = summary.net_bias === 'bearish' ? 'danger' : 'success'
  return (
    <Badge variant={tone} className="gap-2 px-4 py-2 text-sm">
      {label} · {summary.net_strength}
    </Badge>
  )
}

function SetupRow({
  title,
  symbol,
  chips,
  extra,
}: {
  title: string
  symbol: string
  chips: Array<{ label: string; slug?: string | null; interactive: boolean; streak_days: number }>
  extra: number
}) {
  const tone: BadgeProps['variant'] = title === 'Bearish' ? 'danger' : 'success'
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title === 'Bearish' ? <ArrowDownIcon className="h-4 w-4" aria-hidden="true" /> : <ArrowUpIcon className="h-4 w-4" aria-hidden="true" />}
        {title}
      </span>
      {chips.length ? (
        <>
          {chips.map((chip) => {
            const label = `${chip.label} • ${chip.streak_days}d`
            if (chip.interactive && chip.slug) {
              return (
                <Link
                  key={`${title}-${chip.slug}`}
                  href={`/screener?symbol=${encodeURIComponent(symbol)}&focus_slug=${encodeURIComponent(chip.slug)}`}
                  className={badgeVariants({ variant: tone, interactive: true })}
                >
                  {label}
                </Link>
              )
            }
            return (
              <span key={`${title}-${chip.label}`} className={badgeVariants({ variant: tone, interactive: false })}>
                {label}
              </span>
            )
          })}
          {extra > 0 ? <span className="text-xs font-semibold text-muted-foreground">+{extra}</span> : null}
        </>
      ) : (
        <span className="text-xs text-muted-foreground">No setup hits</span>
      )}
    </div>
  )
}

function HitsColumn({ title, hits }: { title: string; hits: SetupHit[] }) {
  if (!hits.length) {
    return (
      <div className="rounded-xl border border-dashed border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
        No {title.toLowerCase()} hits.
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-border/60 bg-background/60 p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="space-y-2">
        {hits.map((hit, idx) => (
          <div key={`${hit.source}-${idx}`} className="flex flex-col gap-1 rounded-lg border border-outline/10 bg-secondary/15 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{hit.source}</div>
                <div className="text-xs text-muted-foreground">
                  {hit.bucket}
                  {hit.style ? ` · ${hit.style}` : ''}
                </div>
              </div>
              <div className="text-right text-xs text-muted-foreground tabular-nums">
                {typeof hit.rank_value === 'number' ? <div>Rank {hit.rank_value}</div> : null}
                <div>W {hit.weight.toFixed(2)}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
