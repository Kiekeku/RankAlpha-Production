'use client'

import { useMemo } from 'react'
import { useRouter } from 'next/navigation'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import { ToastAction } from '@/components/ui/toast'
import { buildComparePageUrl, normalizeCompareSymbol, useCompare } from '@/components/compare/compare_context'
import { cn } from '@/lib/utils'
import { get_tooltip_copy } from '@/lib/tooltip_copy'

export function CompareCheckbox({
  symbol,
  className,
  inputClassName,
  stopPropagation = true,
  tooltipVariant = 'default',
}: {
  symbol: string
  className?: string
  inputClassName?: string
  stopPropagation?: boolean
  tooltipVariant?: 'default' | 'compact'
}) {
  const compare = useCompare()
  const { toast } = useToast()
  const router = useRouter()

  const normalized = useMemo(() => normalizeCompareSymbol(symbol), [symbol])
  const checked = normalized ? compare.symbols.includes(normalized) : false
  const tooltipKey = checked ? 'compare.inCompare' : 'compare.add'
  const tooltipCopy = get_tooltip_copy(tooltipKey)

  const compactLabel = checked ? 'In compare' : 'Add to compare'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'inline-flex h-8 w-8 items-center justify-center rounded-md p-1.5 transition hover:bg-secondary/20',
            className,
          )}
          onClick={
            stopPropagation
              ? (event) => {
                  event.stopPropagation()
                }
              : undefined
          }
          onPointerDown={
            stopPropagation
              ? (event) => {
                  event.stopPropagation()
                }
              : undefined
          }
        >
          <input
            type="checkbox"
            className={cn(
              'h-5 w-5 cursor-pointer rounded-sm accent-primary',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              inputClassName,
            )}
            aria-label={checked ? `Remove ${normalized} from compare` : `Add ${normalized} to compare (max ${compare.max})`}
            checked={checked}
            disabled={!normalized}
            onChange={() => {
              if (!normalized) return
              if (checked) {
                compare.removeSymbol(normalized)
                toast({ title: `Removed ${normalized} from Compare`, duration: 900 })
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
            }}
          />
        </span>
      </TooltipTrigger>
      {tooltipVariant === 'compact' ? (
        <TooltipContent className="px-2 py-1 text-xs">{compactLabel}</TooltipContent>
      ) : (
        <TooltipContent className="max-w-sm px-3 py-2">
          <div className="space-y-1.5">
            <div className="text-xs font-semibold text-foreground">{tooltipCopy.title}</div>
            <div className="text-xs leading-relaxed text-muted-foreground">
              {tooltipKey === 'compare.add' ? tooltipCopy.body.replace('(max 3)', `(max ${compare.max})`) : tooltipCopy.body}
            </div>
          </div>
        </TooltipContent>
      )}
    </Tooltip>
  )
}
