'use client'

import { useSearchParams } from 'next/navigation'
import { ScreenerConsensusView } from '@/features/explore/screener-consensus-view'
import { ScreenerSymbolView } from '@/features/screener/screener-symbol-view'

export function ScreenerPageClient() {
  const searchParams = useSearchParams()
  const symbol = (searchParams.get('symbol') || '').trim().toUpperCase()
  const focusSlug = (searchParams.get('focus_slug') || '').trim().toLowerCase() || undefined
  const origin = (searchParams.get('origin') || '').trim().toLowerCase()
  const originTab = (searchParams.get('origin_tab') || '').trim().toLowerCase()

  return (
    <div className="space-y-4 sm:space-y-6">
      {symbol ? (
        <ScreenerSymbolView symbol={symbol} focusSlug={focusSlug} origin={origin} originTab={originTab} />
      ) : (
        <ScreenerConsensusView />
      )}
    </div>
  )
}
