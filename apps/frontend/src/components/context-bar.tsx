'use client'

import { useMemo, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { GitCompare } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { DataAsOfIndicator } from '@/components/data-asof-indicator'
import { api, type NowcastLatestResponse } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useRegimeLatestIntensity, useRegimeLatestRules } from '@/features/regime/hooks'
import { GlossaryTerm } from '@/components/glossary/GlossaryTerm'
import { TooltipCopyButton } from '@/components/tooltip_copy'
import { isEmptyResponse } from '@/lib/nowcast-utils'
import { useCompare } from '@/components/compare/compare_context'
import { openCompareTray } from '@/components/compare/compare_events'

function toneForRegimeLabel(label: string | null): BadgeProps['variant'] {
  const v = (label || '').trim()
  if (!v) return 'secondary'
  if (v === 'Risk-Off') return 'danger'
  if (v === 'Trend') return 'success'
  if (v === 'Chop') return 'warning'
  return 'info'
}

function toneForNowcastLabel(label: string | null): BadgeProps['variant'] {
  const v = (label || '').toLowerCase()
  if (v.includes('risk_off') || v.includes('risk-off') || v.includes('crisis') || v.includes('stressed') || v.includes('panic')) return 'danger'
  if (v.includes('risk_on') || v.includes('risk-on') || v.includes('easy') || v.includes('calm')) return 'success'
  if (v.includes('transition') || v.includes('fragile') || v.includes('warning') || v.includes('mixed') || v.includes('neutral')) return 'warning'
  return 'secondary'
}

function prettyNowcastLabel(label: string) {
  const raw = label.trim()
  if (!raw) return '-'
  const normalized = raw.replace(/[_-]/g, ' ').toLowerCase()
  if (normalized === 'risk off') return 'Risk-Off'
  if (normalized === 'risk on') return 'Risk-On'
  if (normalized === 'mixed' || normalized === 'neutral') return 'Mixed'
  return normalized
    .split(' ')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

export function ContextBar({ className }: { className?: string }) {
  const router = useRouter()
  const compare = useCompare()
  const { data: rulesLatest } = useRegimeLatestRules()
  const { data: intensityLatest } = useRegimeLatestIntensity()
  const { data: nowcastLatest } = useQuery<NowcastLatestResponse>({
    queryKey: ['overview', 'headlines', 'nowcast-latest'],
    queryFn: () => api.getNowcastLatest({ trail_days: 30 }),
    staleTime: 5 * 60_000,
  })

  const regimeLabel = (() => {
    if (rulesLatest && !isEmptyResponse(rulesLatest)) {
      return rulesLatest.label ?? null
    }
    if (intensityLatest && !isEmptyResponse(intensityLatest)) {
      return intensityLatest.regime_label ?? null
    }
    return null
  })()

  const nowcastRawLabel =
    nowcastLatest && !isEmptyResponse(nowcastLatest) ? nowcastLatest.nowcast_label ?? null : null
  const nowcastLabel = nowcastRawLabel ? prettyNowcastLabel(nowcastRawLabel) : null

  const { data: universe } = useQuery({
    queryKey: ['context-bar-universe-size'],
    queryFn: async () => {
      const res = await api.getStockGrades({ limit: 1, skip: 0 })
      const total = Number(res?.total_count)
      return Number.isFinite(total) ? total : null
    },
    staleTime: 5 * 60_000,
  })

  const items = useMemo(() => {
    const out: Array<{ key: string; node: ReactNode }> = []
    out.push({ key: 'asof', node: <DataAsOfIndicator /> })
    if (regimeLabel) {
      out.push({
        key: 'regime',
        node: (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="hidden sm:inline">Regime</span>
            <Badge variant={toneForRegimeLabel(regimeLabel)} className="px-2 py-0.5 text-[11px] font-semibold">
              <GlossaryTerm term={regimeLabel} className="text-inherit no-underline" />
            </Badge>
          </div>
        ),
      })
    }
    if (nowcastLabel) {
      out.push({
        key: 'nowcast',
        node: (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="hidden sm:inline">Nowcast</span>
            <Badge variant={toneForNowcastLabel(nowcastRawLabel)} className="px-2 py-0.5 text-[11px] font-semibold">
              <GlossaryTerm term={nowcastLabel} className="text-inherit no-underline" />
            </Badge>
          </div>
        ),
      })
    }
    if (universe != null) {
      out.push({
        key: 'universe',
        node: (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="hidden sm:inline">Universe</span>
            <span className="font-semibold text-foreground tabular-nums">{universe.toLocaleString()}</span>
            <TooltipCopyButton
              tooltipKey="global.universe"
              iconSize="h-3.5 w-3.5"
              buttonClassName="text-muted-foreground hover:text-foreground"
            />
          </div>
        ),
      })
    }
    return out
  }, [nowcastLabel, nowcastRawLabel, regimeLabel, universe])

  return (
    <div className={cn('border-b border-border/50 bg-background/70 backdrop-blur', className)}>
      <div className="container flex flex-wrap items-center gap-3 py-1.5">
        <div className="flex flex-wrap items-center gap-3">
          {items.map((it) => (
            <div key={it.key} className="flex items-center gap-3">
              {it.node}
            </div>
          ))}
        </div>
        <div className="ml-auto hidden items-center md:flex">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-full border border-outline/10 bg-card px-3 py-1 text-xs font-semibold text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            aria-label={`Open Compare (${compare.symbols.length}/${compare.max})`}
            onClick={() => {
              if (compare.symbols.length > 0) {
                openCompareTray()
                return
              }
              router.push('/compare')
            }}
          >
            <GitCompare className="h-3.5 w-3.5" aria-hidden />
            Compare {compare.symbols.length}/{compare.max}
          </button>
        </div>
      </div>
    </div>
  )
}
