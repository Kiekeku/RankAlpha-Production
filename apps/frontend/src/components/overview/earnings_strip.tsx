'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'

import { api, type UpcomingEarningsResponse } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useIsDesktop } from '@/lib/use_media_query'
import { FIVE_MIN_MS } from '@/lib/time'
import { cn } from '@/lib/utils'
import { formatEasternDate } from '@/lib/date'

const DEFAULT_TRADING_DAYS = 3
const DEFAULT_MIN_MARKET_CAP = 2_000_000_000

function formatEarningsTime(value?: string | null) {
  const raw = (value || '').trim()
  if (!raw) return null
  const normalized = raw.toLowerCase()
  if (normalized === 'bmo') return 'BMO'
  if (normalized === 'amc') return 'AMC'
  if (normalized === 'dmh') return 'DMH'
  return raw.toUpperCase()
}

function formatMonthDay(isoDate: string) {
  const parts = (isoDate || '').split('-')
  if (parts.length !== 3) return isoDate
  const monthIndex = Number(parts[1]) - 1
  const day = Number(parts[2])
  if (Number.isNaN(monthIndex) || Number.isNaN(day)) return isoDate
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const label = months[monthIndex]
  if (!label) return isoDate
  return `${label} ${day}`
}

type EarningsGroup = {
  date: string
  items: UpcomingEarningsResponse['items']
}

export function EarningsStrip() {
  const [showAllToday, setShowAllToday] = useState(false)
  const isDesktop = useIsDesktop()
  const todayLimit = isDesktop ? 10 : 5

  const { data, isLoading } = useQuery<UpcomingEarningsResponse>({
    queryKey: ['overview', 'earnings', 'upcoming', DEFAULT_TRADING_DAYS, DEFAULT_MIN_MARKET_CAP],
    queryFn: () =>
      api.getUpcomingEarnings({
        days: DEFAULT_TRADING_DAYS,
        min_market_cap: DEFAULT_MIN_MARKET_CAP,
      }),
    staleTime: FIVE_MIN_MS,
  })

  const groups = useMemo<EarningsGroup[]>(() => {
    const items = data?.items ?? []
    if (!items.length) return []
    const map = new Map<string, UpcomingEarningsResponse['items']>()
    items.forEach((item) => {
      const key = item.earnings_date
      if (!key) return
      const existing = map.get(key) ?? []
      existing.push(item)
      map.set(key, existing)
    })
    return Array.from(map.entries()).map(([date, items]) => ({ date, items }))
  }, [data])

  const todayIso = formatEasternDate(new Date())

  return (
    <div className="rounded-2xl border border-outline/10 bg-card p-3">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Upcoming earnings</div>
        <div className="text-[11px] text-muted-foreground">Mid + large cap focus · today + next 2 trading days</div>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {isLoading ? (
          <>
            <Skeleton className="h-10 w-44 rounded-xl" />
            <Skeleton className="h-10 w-44 rounded-xl" />
            <Skeleton className="h-10 w-44 rounded-xl" />
          </>
        ) : groups.length ? (
          groups.map((group) => (
            <details
              key={group.date}
              open={group.date === todayIso}
              className={cn('rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2')}
            >
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 marker:hidden">
                <Badge variant="outline" className="text-[11px] font-semibold">
                  {formatMonthDay(group.date)}
                </Badge>
                <span className="text-[11px] text-muted-foreground">{group.items.length} tickers</span>
                {group.date === todayIso ? (
                  <Badge variant="info" className="text-[10px] font-semibold uppercase tracking-wide">
                    Today
                  </Badge>
                ) : null}
              </summary>
              <div className="mt-2 flex flex-wrap items-center gap-1">
                {(group.date === todayIso && !showAllToday
                  ? group.items.slice(0, todayLimit)
                  : group.items
                ).map((item) => {
                  const time = formatEarningsTime(item.earnings_time)
                  const label = time ? `${item.symbol} · ${time}` : item.symbol
                  return (
                    <Link key={`${group.date}-${item.symbol}`} href={`/ticker/${encodeURIComponent(item.symbol)}`}>
                      <Badge variant="secondary" interactive className="text-[11px] font-semibold">
                        {label}
                      </Badge>
                    </Link>
                  )
                })}
              </div>
              {group.date === todayIso && group.items.length > todayLimit ? (
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={() => setShowAllToday((prev) => !prev)}
                    className="text-[11px] font-semibold text-primary hover:underline"
                  >
                    {showAllToday ? 'Show fewer' : `Show ${group.items.length - todayLimit} more`}
                  </button>
                </div>
              ) : null}
            </details>
          ))
        ) : (
          <div className="rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2 text-xs text-muted-foreground">
            No mid/large-cap earnings for today + the next 2 trading days.
          </div>
        )}
      </div>
    </div>
  )
}
