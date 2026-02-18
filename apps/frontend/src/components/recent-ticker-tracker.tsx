'use client'

import { useEffect } from 'react'
import { addRecentTicker } from '@/lib/command_bar'

export function RecentTickerTracker({ symbol, companyName }: { symbol: string; companyName?: string }) {
  useEffect(() => {
    addRecentTicker({ symbol, company_name: companyName })
  }, [symbol, companyName])

  return null
}

