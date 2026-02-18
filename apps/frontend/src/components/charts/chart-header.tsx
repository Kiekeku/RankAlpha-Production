'use client'

import type { ReactNode } from 'react'

import Link from 'next/link'

import { TooltipCopyButton } from '@/components/tooltip_copy'
import type { TooltipKey } from '@/lib/tooltip_copy'
import { ChartLegend, type ChartLegendItem } from '@/components/charts/chart-legend'
import { ChartTimeframeControl, type ChartTimeframeOption } from '@/components/charts/chart-timeframe-control'
import { InfoTooltipButton } from '@/components/info_tooltip_button'
import { cn } from '@/lib/utils'

export function ChartHeader({
  title,
  description,
  subtitle,
  stats,
  tooltipKey,
  tooltipLabel,
  updatedAt,
  methodologyHref,
  methodologyLabel = 'Methodology',
  timeframes,
  activeTimeframe,
  onTimeframeChange,
  timeframeLabel,
  timeframeHelp,
  legend,
  actions,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  subtitle?: string | null
  stats?: ReactNode
  tooltipKey?: TooltipKey
  tooltipLabel?: string
  updatedAt?: string | null
  methodologyHref?: string
  methodologyLabel?: string
  timeframes?: ChartTimeframeOption[]
  activeTimeframe?: string
  onTimeframeChange?: (next: string) => void
  timeframeLabel?: string
  timeframeHelp?: string
  legend?: ChartLegendItem[]
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between', className)}>
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 text-sm font-semibold text-foreground">
            <span className="inline-flex items-center gap-2">{title}</span>
            {tooltipKey ? (
              <TooltipCopyButton
                tooltipKey={tooltipKey}
                label={tooltipLabel ?? (typeof title === 'string' ? title : 'Chart')}
                iconSize="h-3.5 w-3.5"
                buttonClassName="text-muted-foreground hover:text-foreground"
              />
            ) : null}
          </div>
          {stats ? <span className="text-sm font-semibold tabular-nums text-foreground">{stats}</span> : null}
          {subtitle ? <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{subtitle}</span> : null}
        </div>
        {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
        {updatedAt || methodologyHref ? (
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            {updatedAt ? <span>As of {updatedAt}</span> : null}
            {methodologyHref ? (
              <Link href={methodologyHref} className="font-semibold text-muted-foreground hover:text-foreground">
                {methodologyLabel}
              </Link>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {timeframes && activeTimeframe && onTimeframeChange ? (
          <div className="flex items-center gap-2">
            {timeframeLabel ? (
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{timeframeLabel}</span>
            ) : null}
            {timeframeHelp ? (
              <InfoTooltipButton
                label={timeframeLabel ?? 'Window'}
                description={timeframeHelp}
                iconSize="h-3 w-3"
                buttonClassName="text-muted-foreground hover:text-foreground"
              />
            ) : null}
            <ChartTimeframeControl options={timeframes} active={activeTimeframe} onChange={onTimeframeChange} />
          </div>
        ) : null}
        {legend ? <ChartLegend items={legend} /> : null}
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  )
}
