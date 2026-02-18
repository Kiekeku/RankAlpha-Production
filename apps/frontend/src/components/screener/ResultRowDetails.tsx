import type { ReactNode } from 'react'

import type { ScreenerConsensusItem } from '@/lib/api'
import { formatEasternDate } from '@/lib/date'
import { formatNumberValue, formatPct } from '@/lib/format'
import { cn } from '@/lib/utils'

function DetailBlock({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-xs text-foreground">{children}</div>
    </div>
  )
}

function DetailChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-2 py-1 text-[11px] text-muted-foreground">
      <span className="font-semibold text-foreground">{label}</span>
      <span>{value}</span>
    </div>
  )
}

export function ResultRowDetails({ row }: { row: ScreenerConsensusItem }) {
  const primaryStyle = row.primary_style?.trim()
  const primarySource = row.primary_source?.trim()
  const screensLong = row.screens_count_long ?? null
  const screensShort = row.screens_count_short ?? null
  const tiersLong = row.tier12_hits_long ?? null
  const tiersShort = row.tier12_hits_short ?? null

  const thresholdChips = [
    { label: 'Appear', value: formatNumberValue(row.appearances ?? null, 1) },
    { label: 'Styles', value: formatNumberValue(row.styles_distinct ?? null, 1) },
    { label: 'Sources', value: formatNumberValue(row.sources_distinct ?? null, 1) },
    { label: 'Best rank', value: formatNumberValue(row.rank_best ?? null, 0) },
    { label: 'Best %ile', value: formatPct(row.min_style_rank_pct, 1) },
    { label: 'Consensus', value: formatNumberValue(row.consensus_score ?? null, 0) },
  ].filter((chip) => chip.value !== '-')

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <DetailBlock label="Triggering screeners">
        {primaryStyle || primarySource ? (
          <div className="space-y-1">
            <div>
              Primary: {primaryStyle || '-'} / {primarySource || '-'}
            </div>
            <div className="text-[11px] text-muted-foreground">
              Screen hits: {formatNumberValue(screensLong, 0)} long · {formatNumberValue(screensShort, 0)} short
            </div>
            {Number.isFinite(Number(tiersLong)) || Number.isFinite(Number(tiersShort)) ? (
              <div className="text-[11px] text-muted-foreground">
                Tier 1–2: {formatNumberValue(tiersLong, 0)} long · {formatNumberValue(tiersShort, 0)} short
              </div>
            ) : null}
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">Primary screener not available.</span>
        )}
      </DetailBlock>

      <DetailBlock label="Dates">
        <div>As of {formatEasternDate(row.as_of_date)}</div>
      </DetailBlock>

      <DetailBlock label="Key thresholds met">
        {thresholdChips.length ? (
          <div className="flex flex-wrap gap-2">
            {thresholdChips.map((chip) => (
              <DetailChip key={chip.label} label={chip.label} value={chip.value} />
            ))}
          </div>
        ) : (
          <span className={cn('text-xs text-muted-foreground')}>No thresholds available.</span>
        )}
      </DetailBlock>
    </div>
  )
}
