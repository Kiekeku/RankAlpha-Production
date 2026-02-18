'use client'

import { useMemo, useState } from 'react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { TooltipCopyButton } from '@/components/tooltip_copy'
import type { TooltipKey } from '@/lib/tooltip_copy'
import { ResponsiveSparklineMini } from '@/features/stock-detail/responsive_sparkline_mini'
import { ClickableCard } from '@/components/interaction/clickable_card'
import { cn } from '@/lib/utils'

type SparkPoint = { x: string; y: number }

export type TechnicalIndicatorTilesProps = {
  rsi: { value?: number | null; data: SparkPoint[] }
  macdHist: { value?: number | null; data: SparkPoint[]; maxAbs: number }
  atr: { value?: number | null; data: SparkPoint[] }
}

type DialogMetric = 'rsi' | 'macd_hist' | 'atr' | null

function formatValue(value: number | null | undefined, decimals: number) {
  if (value === null || value === undefined) return '-'
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return num.toFixed(decimals)
}

type MetricCard = {
  key: 'rsi' | 'macd_hist' | 'atr'
  title: string
  value: string
  data: SparkPoint[]
  color: string
  domainY?: [number, number]
  neutralBand?: [number, number]
  format: (y: number) => string
  tooltipKey?: TooltipKey
}

export function TechnicalIndicatorTiles({ rsi, macdHist, atr }: TechnicalIndicatorTilesProps) {
  const [openMetric, setOpenMetric] = useState<DialogMetric>(null)

  const metrics = useMemo<MetricCard[]>(
    () => [
      {
        key: 'rsi' as const,
        title: 'RSI (14)',
        value: formatValue(rsi.value, 1),
        data: rsi.data,
        color: '#0ea5e9',
        domainY: [0, 100] as [number, number],
        neutralBand: [30, 70] as [number, number],
        format: (y: number) => y.toFixed(1),
        tooltipKey: 'chart.rsi',
      },
      {
        key: 'macd_hist' as const,
        title: 'MACD Hist',
        value: formatValue(macdHist.value, 3),
        data: macdHist.data,
        color: '#a78bfa',
        domainY: [-macdHist.maxAbs, macdHist.maxAbs] as [number, number],
        neutralBand: undefined,
        format: (y: number) => y.toFixed(3),
        tooltipKey: 'chart.macdHist',
      },
      {
        key: 'atr' as const,
        title: 'ATR (14)',
        value: formatValue(atr.value, 2),
        data: atr.data,
        color: '#f97316',
        domainY: undefined,
        neutralBand: undefined,
        format: (y: number) => y.toFixed(2),
        tooltipKey: 'chart.atr',
      },
    ],
    [atr.data, atr.value, macdHist.data, macdHist.maxAbs, macdHist.value, rsi.data, rsi.value],
  )

  const active = metrics.find((m) => m.key === openMetric) ?? null

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-3">
        {metrics.map((m) => (
          <ClickableCard
            key={m.key}
            onActivate={() => setOpenMetric(m.key)}
            className={cn(
              'group rounded-lg border border-outline/10 bg-secondary/15 p-3 text-left',
              'shadow-none ring-0',
              'hover:border-outline/16 hover:bg-secondary/22 hover:shadow-sm',
            )}
            aria-label={`Expand chart for ${m.title}`}
          >
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(120px,180px)] sm:items-center">
              <div className="min-w-0 pr-2">
                <div className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground group-hover:underline">
                  <span>{m.title}</span>
                  {m.tooltipKey ? (
                    <TooltipCopyButton
                      tooltipKey={m.tooltipKey}
                      label={m.title}
                      iconSize="h-3.5 w-3.5"
                      buttonClassName="text-muted-foreground hover:text-foreground"
                    />
                  ) : null}
                </div>
                <div className="mt-1 text-lg font-semibold">{m.value}</div>
              </div>
              <div className="flex min-w-0 justify-end">
                <ResponsiveSparklineMini
                  data={m.data}
                  height={64}
                  domainY={m.domainY}
                  neutralBand={m.neutralBand}
                  color={m.color}
                  label={m.title}
                  maxWidth={180}
                  minWidth={120}
                  format={m.format}
                />
              </div>
            </div>
          </ClickableCard>
        ))}
      </div>

      <Dialog open={openMetric !== null} onOpenChange={(next) => setOpenMetric(next ? openMetric : null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span>{active?.title ?? 'Chart'}</span>
              {active?.tooltipKey ? (
                <TooltipCopyButton
                  tooltipKey={active.tooltipKey}
                  label={active.title}
                  iconSize="h-3.5 w-3.5"
                  buttonClassName="text-muted-foreground hover:text-foreground"
                />
              ) : null}
            </DialogTitle>
          </DialogHeader>
          <div className="rounded-xl border border-outline/10 bg-card p-4">
            <div className="mb-3 text-sm text-muted-foreground">
              Current: <span className="font-semibold text-foreground">{active?.value ?? '-'}</span>
            </div>
            {active ? (
              <ResponsiveSparklineMini
                data={active.data}
                height={220}
                domainY={active.domainY}
                neutralBand={active.neutralBand}
                color={active.color}
                label={active.title}
                maxWidth={880}
                minWidth={320}
                format={active.format}
              />
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
