'use client'

import { useEffect, useRef, useState } from 'react'
import { ChartFrame } from '@/components/charts/chart-frame'
import { ChartHeader } from '@/components/charts/chart-header'
import { PriceHistoryMini, PRICE_HISTORY_SMA_CONFIGS } from '@/components/price-history-mini'
import { RedactedOverlay } from '@/components/ui/redacted'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'

export function StockPriceHistoryCard({ symbol }: { symbol: string }) {
  const normalizedSymbol = (symbol || '').trim().toUpperCase()
  const [timeframe, setTimeframe] = useState<'1M' | '3M' | '1Y'>('1Y')
  const daysByTf: Record<'1M' | '3M' | '1Y', number> = { '1M': 22, '3M': 66, '1Y': 252 }
  const labelByTf: Record<'1M' | '3M' | '1Y', string> = { '1M': 'Past Month', '3M': 'Past 3 Months', '1Y': 'Past Year' }
  const timeframes = (['1M', '3M', '1Y'] as const).map((tf) => ({ key: tf, label: labelByTf[tf] }))
  const chartContainerRef = useRef<HTMLDivElement | null>(null)
  const [chartWidth, setChartWidth] = useState(360)
  const [chartStats, setChartStats] = useState<{ change: number; changePct: number; up: boolean; subtitle: string | null } | null>(null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const el = chartContainerRef.current
    if (!el) return

    const clamp = (value: number) => Math.max(260, Math.min(720, Math.floor(value)))
    const update = (nextWidth: number) => {
      const candidate = clamp(nextWidth)
      setChartWidth((prev) => (prev === candidate ? prev : candidate))
    }

    update(el.getBoundingClientRect().width)

    if (typeof ResizeObserver === 'undefined') {
      const onResize = () => update(el.getBoundingClientRect().width)
      window.addEventListener('resize', onResize)
      return () => window.removeEventListener('resize', onResize)
    }

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      update(entry.contentRect.width)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const changeLabel = chartStats
    ? SHOW_RAW_DATA
      ? `${chartStats.change >= 0 ? '+' : ''}${chartStats.change.toFixed(2)} (${chartStats.changePct.toFixed(1)}%)`
      : (
        <span className="blur-sm select-none text-muted-foreground">****</span>
      )
    : null
  const subtitle = chartStats?.subtitle ? `${labelByTf[timeframe]} · ${chartStats.subtitle}` : labelByTf[timeframe]
  const priceLegendColor = chartStats?.up ? 'hsl(var(--status-success))' : 'hsl(var(--status-danger))'

  return (
    <ChartFrame
      className="mt-2"
      header={(
        <ChartHeader
          title={SHOW_RAW_DATA ? 'Price history' : 'Price trend'}
          description={SHOW_RAW_DATA ? undefined : 'Raw prices hidden. Trend indexed to 100.'}
          subtitle={subtitle}
          stats={changeLabel}
          tooltipKey="chart.priceHistory"
          timeframes={timeframes}
          activeTimeframe={timeframe}
          onTimeframeChange={(next) => setTimeframe(next as '1M' | '3M' | '1Y')}
          legend={[
            { label: SHOW_RAW_DATA ? 'Price' : 'Index', color: priceLegendColor, emphasis: 'primary' },
            ...PRICE_HISTORY_SMA_CONFIGS.map((cfg) => ({ label: cfg.label, color: cfg.color, emphasis: 'secondary' as const })),
          ]}
        />
      )}
    >
      <div ref={chartContainerRef} className="relative">
        <PriceHistoryMini
          symbol={normalizedSymbol}
          days={daysByTf[timeframe]}
          width={chartWidth}
          height={180}
          showLabel={false}
          showChange={false}
          onStats={(s) =>
            setChartStats((prev) =>
              prev && prev.change === s.change && prev.changePct === s.changePct && prev.up === s.up && prev.subtitle === s.subtitle
                ? prev
                : { change: s.change, changePct: s.changePct, up: s.up, subtitle: s.subtitle ?? null }
            )
          }
        />
        {!SHOW_RAW_DATA ? <RedactedOverlay /> : null}
      </div>
    </ChartFrame>
  )
}
