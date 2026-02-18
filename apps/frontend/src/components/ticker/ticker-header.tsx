import type { ReactNode } from 'react'

import { LineChartIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { PrimaryCtaLink } from '@/components/primary-cta'
import { TickerQuickActions } from '@/components/ticker/ticker-quick-actions'
import { TickerTabNav } from '@/components/ticker/ticker-tab-nav'
import { LivePriceBlock } from '@/features/stock-detail/live_price_block'
import { formatEasternDate } from '@/lib/date'
import { cn } from '@/lib/utils'

export function TickerHeader({
  symbol,
  companyName,
  exchange,
  sector,
  grade,
  gradeClassName,
  priceAsOf,
  tabs,
  activeTab,
  canonicalPath,
  showTabs = true,
  summaryStrip,
  chartHref,
  variant = 'page',
}: {
  symbol: string
  companyName?: string | null
  exchange?: string | null
  sector?: string | null
  grade?: string | null
  gradeClassName?: string
  priceAsOf?: string | null
  tabs?: Array<{ key: string; label: string }>
  activeTab?: string
  canonicalPath: string
  showTabs?: boolean
  summaryStrip?: ReactNode
  chartHref: string
  variant?: 'page' | 'modal' | 'panel'
}) {
  const isCompact = variant !== 'page'
  const metadata = [exchange?.trim(), sector?.trim()].filter(Boolean)

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn('font-semibold tracking-tight', isCompact ? 'text-xl' : 'text-3xl')}>
              {symbol}
            </span>
            {grade ? (
              <Badge className={cn(gradeClassName, 'px-3 py-1 text-sm')}>Grade {grade}</Badge>
            ) : null}
          </div>
          {companyName ? (
            <div className={cn('min-w-0 break-words leading-tight text-muted-foreground', isCompact ? 'text-sm' : 'text-base')}>
              {companyName}
            </div>
          ) : null}
          {metadata.length ? (
            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
              <span>{metadata.join(' • ')}</span>
            </div>
          ) : null}
        </div>
        <PrimaryCtaLink href={chartHref} aria-label={`View chart for ${symbol}`}>
          <LineChartIcon className="h-4 w-4" aria-hidden />
          View Chart
        </PrimaryCtaLink>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <LivePriceBlock symbol={symbol} />
          <span className="text-xs text-muted-foreground">
            As of {priceAsOf ? formatEasternDate(priceAsOf) : '-'}
          </span>
        </div>
        <TickerQuickActions
          symbol={symbol}
          canonicalPath={canonicalPath}
        />
      </div>

      {showTabs && tabs && activeTab ? (
        <TickerTabNav tabs={tabs} activeTab={activeTab} canonicalPath={canonicalPath} />
      ) : null}

      {summaryStrip ? (
        <div className="rounded-xl border border-outline/10 bg-secondary/10 px-3 py-2">
          {summaryStrip}
        </div>
      ) : null}
    </section>
  )
}
