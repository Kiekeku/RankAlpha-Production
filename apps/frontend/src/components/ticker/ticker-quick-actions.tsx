'use client'

import { useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { GitCompare, Link2Icon } from 'lucide-react'

import { ToastAction } from '@/components/ui/toast'
import { useToast } from '@/components/ui/use-toast'
import { buildComparePageUrl, normalizeCompareSymbol, useCompare } from '@/components/compare/compare_context'
import { openCompareTray } from '@/components/compare/compare_events'
import { cn } from '@/lib/utils'

export function TickerQuickActions({
  symbol,
  canonicalPath,
  className,
}: {
  symbol: string
  canonicalPath: string
  className?: string
}) {
  const { toast } = useToast()
  const router = useRouter()
  const compare = useCompare()
  const normalized = useMemo(() => normalizeCompareSymbol(symbol), [symbol])
  const isInCompare = normalized ? compare.symbols.includes(normalized) : false

  const shareLink = async () => {
    try {
      const href = window.location.href
      await navigator.clipboard.writeText(href)
      toast({ title: 'Link copied', description: canonicalPath })
    } catch {
      toast({ title: 'Copy failed', description: 'Clipboard access was blocked.' })
    }
  }

  const actionClass = cn(
    'inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground transition hover:text-foreground',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
  )

  const handleCompareClick = () => {
    if (!normalized) {
      toast({ title: 'Invalid ticker', description: 'Try a different symbol.', duration: 2000 })
      return
    }
    if (isInCompare) {
      openCompareTray()
      return
    }

    const res = compare.addSymbol(normalized)
    if (res === 'full') {
      const href = buildComparePageUrl({
        symbols: compare.symbols,
        baseline: compare.baseline ?? (compare.symbols[0] ?? null),
        mode: 'table',
        deltas: compare.showDeltas,
      })
      toast({
        title: `Compare supports up to ${compare.max} symbols.`,
        description: 'Remove one to add another.',
        duration: 4000,
        action: (
          <ToastAction altText="Open compare" onClick={() => router.push(href)}>
            Open Compare
          </ToastAction>
        ),
      })
      return
    }
    if (res === 'invalid') {
      toast({ title: 'Invalid ticker', description: 'Try a different symbol.', duration: 2000 })
      return
    }

    toast({ title: `Added ${normalized} to Compare`, duration: 900 })
    openCompareTray()
  }

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      <button
        type="button"
        className={actionClass}
        onClick={handleCompareClick}
        aria-label={isInCompare ? `Open Compare (${compare.symbols.length} of ${compare.max})` : `Add ${normalized || symbol} to compare`}
      >
        <GitCompare className="h-3.5 w-3.5" aria-hidden />
        {isInCompare ? 'In Compare' : 'Compare'}
      </button>
      <button
        type="button"
        className={actionClass}
        onClick={shareLink}
        aria-label="Share link"
      >
        <Link2Icon className="h-3.5 w-3.5" aria-hidden />
        Share
      </button>
    </div>
  )
}
