'use client'

import { useEffect, useState } from 'react'
import { ChevronRightIcon, WalletIcon } from 'lucide-react'

import { formatEasternDate } from '@/lib/date'
import {
  formatCompactCount,
  formatNumberValue,
  formatSignedPercent,
  formatUsdCompactFromMillions,
} from '@/features/stock-detail/stock_detail_format'
import { SHOW_RAW_DATA } from '@/lib/feature_flags'
import { RedactedOverlay } from '@/components/ui/redacted'

const STORAGE_KEY = 'rankalpha.ticker.fundamentals.open.v1'

export function TickerFundamentalsDetails({
  latestAsOfDate,
  fundamentalsByCode,
  peIsDerived,
  pfcfIsDerived,
  peTtmValue,
  pfcfValue,
  hasData,
  isRedacted,
}: {
  latestAsOfDate?: string | null
  fundamentalsByCode: Record<string, number | null | undefined>
  peIsDerived: boolean
  pfcfIsDerived: boolean
  peTtmValue: number | null
  pfcfValue: number | null
  hasData: boolean
  isRedacted?: boolean
  redactionReason?: string | null
}) {
  const [open, setOpen] = useState(true)
  const redacted = Boolean(isRedacted || !SHOW_RAW_DATA)

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      if (raw === '0' || raw === 'false') setOpen(false)
      if (raw === '1' || raw === 'true') setOpen(true)
    } catch {
      // ignore storage failures
    }
  }, [])

  return (
    <details
      open={open}
      onToggle={(event) => {
        const nextOpen = (event.currentTarget as HTMLDetailsElement).open
        setOpen(nextOpen)
        try {
          window.localStorage.setItem(STORAGE_KEY, nextOpen ? '1' : '0')
        } catch {
          // ignore storage failures
        }
      }}
      className="group mt-4 rounded-xl border border-outline/10 bg-card p-3"
    >
      <summary className="flex list-none cursor-pointer items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <WalletIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
            Fundamentals (TTM)
          </div>
          <div className="text-xs text-muted-foreground">
            {latestAsOfDate ? `As of ${formatEasternDate(latestAsOfDate)}` : 'As of -'}
          </div>
        </div>
        <ChevronRightIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
      </summary>
      <div className="mt-3">
        {redacted ? (
          <div className="relative">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <TechStat label="Market Cap" value="****" blurred />
              <TechStat label="Beta" value="****" blurred />
              <TechStat label="Shares Out" value="****" blurred />
              <TechStat label="P/E (TTM)" value="****" blurred />
              <TechStat label="P/S (TTM)" value="****" blurred />
              <TechStat label="P/FCF (TTM)" value="****" blurred />
              <TechStat label="Rev YoY" value="****" blurred />
              <TechStat label="EPS YoY" value="****" blurred />
              <TechStat label="Gross Margin" value="****" blurred />
              <TechStat label="Op Margin" value="****" blurred />
              <TechStat label="Net Debt" value="****" blurred />
              <TechStat label="Current Ratio" value="****" blurred />
            </div>
            <RedactedOverlay />
          </div>
        ) : !hasData ? (
          <p className="text-sm text-muted-foreground">No fundamentals available for this symbol yet.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <TechStat label="Market Cap" value={formatUsdCompactFromMillions(fundamentalsByCode['mktcap'])} />
            <TechStat label="Beta" value={formatNumberValue(fundamentalsByCode['beta'], 2)} />
            <TechStat label="Shares Out" value={formatCompactCount(fundamentalsByCode['sharesoutstanding'])} />
            <TechStat
              label={peIsDerived ? 'P/E (TTM) · Derived' : 'P/E (TTM)'}
              value={formatNumberValue(peTtmValue, 1)}
            />
            <TechStat label="P/S (TTM)" value={formatNumberValue(fundamentalsByCode['ttmpr2rev'], 2)} />
            <TechStat
              label={pfcfIsDerived ? 'P/FCF (TTM) · Derived' : 'P/FCF (TTM)'}
              value={formatNumberValue(pfcfValue, 2)}
            />
            <TechStat label="Rev YoY" value={formatSignedPercent(fundamentalsByCode['revchngyr'], 1)} />
            <TechStat label="EPS YoY" value={formatSignedPercent(fundamentalsByCode['epschngyr'], 1)} />
            <TechStat label="Gross Margin" value={formatSignedPercent(fundamentalsByCode['ttmgrosmgn'], 1)} />
            <TechStat label="Op Margin" value={formatSignedPercent(fundamentalsByCode['ttmopmgn'], 1)} />
            <TechStat label="Net Debt" value={formatUsdCompactFromMillions(fundamentalsByCode['netdebt_a'])} />
            <TechStat label="Current Ratio" value={formatNumberValue(fundamentalsByCode['qcurratio'], 2)} />
          </div>
        )}
      </div>
    </details>
  )
}

function TechStat({ label, value, blurred }: { label: string; value: string; blurred?: boolean }) {
  return (
    <div className="rounded-lg border border-outline/10 bg-card p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 text-sm font-semibold ${blurred ? 'blur-sm select-none text-muted-foreground/70' : ''}`}>{value}</div>
    </div>
  )
}
