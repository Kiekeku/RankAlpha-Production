'use client'

import { useEffect, useMemo, useState } from 'react'
import { BookOpenIcon, SearchIcon, XIcon } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { cn } from '@/lib/utils'
import { useGlossary } from '@/components/glossary/glossary_context'
import { TooltipCopy } from '@/components/tooltip_copy'
import { UI_TERMS } from '@/lib/ui_terms'

type GlossaryItem = {
  term: string
  definition: string
  category: 'Liquidity' | 'Funding' | 'Credit' | 'Volatility' | 'Rates & FX' | 'Breadth' | 'Structure' | 'Regime' | 'Screener' | 'AI'
  learnMorePath?: string
}

const GLOSSARY: GlossaryItem[] = [
  { term: 'ON RRP', category: 'Liquidity', definition: 'Fed overnight reverse repo facility usage (cash parked at the Fed).' },
  { term: 'TGA', category: 'Liquidity', definition: 'Treasury General Account balance (US Treasury cash at the Fed).' },
  { term: 'Net Liquidity', category: 'Liquidity', definition: 'A liquidity proxy combining Fed balance sheet, TGA, and RRP components.' },

  { term: 'FRA–OIS', category: 'Funding', definition: 'Funding stress spread: forward rate agreement minus overnight indexed swap.' },
  { term: 'SOFR', category: 'Funding', definition: 'Secured Overnight Financing Rate (broad Treasury repo funding rate).' },

  { term: 'HY OAS', category: 'Credit', definition: 'High-yield option-adjusted spread over Treasuries (credit stress proxy).' },
  { term: 'OAS', category: 'Credit', definition: 'Option-adjusted spread: spread over risk-free curve adjusting for embedded options.' },

  { term: 'VIX', category: 'Volatility', definition: 'Implied volatility index for S&P 500 options (30-day expected vol).' },
  { term: 'VRP', category: 'Volatility', definition: 'Volatility risk premium: implied vol minus realized vol (pricing of vol).' },

  { term: '2s10s', category: 'Rates & FX', definition: 'Yield curve slope: 10-year minus 2-year Treasury yield.' },
  { term: 'TIPS', category: 'Rates & FX', definition: 'Treasury Inflation-Protected Securities (real yields / breakevens).' },
  { term: '$USDX', category: 'Rates & FX', definition: 'US Dollar Index (broad USD strength vs a basket of currencies).' },

  { term: 'A/D', category: 'Breadth', definition: 'Advance/decline ratio: advancers divided by decliners (breadth proxy).' },
  { term: 'Breadth', category: 'Breadth', definition: 'How widely participation is distributed across stocks (not just mega-caps).' },

  { term: 'CVD', category: 'Structure', definition: 'Cumulative volume delta: buy-initiated minus sell-initiated volume over time.' },

  { term: 'RS', category: 'Regime', definition: 'Regime Score: net flow composite used by the rules-based regime model.', learnMorePath: '/about/regime' },
  { term: 'Trend', category: 'Regime', definition: 'Risk-on / trending tape: breakouts and continuation setups tend to work better.', learnMorePath: '/about/regime' },
  { term: 'Chop', category: 'Regime', definition: 'Choppy / mixed tape: mean reversion dominates and breakouts fail more often.', learnMorePath: '/about/regime' },
  { term: 'Risk-Off', category: 'Regime', definition: 'Risk-off tape: defensive posture, breakdown risk elevated and leaders can unwind.', learnMorePath: '/about/nowcast' },
  { term: 'Risk-On', category: 'Regime', definition: 'Risk-on tape: participation broadens and trend-following setups perform better.', learnMorePath: '/about/nowcast' },
  { term: 'Mixed', category: 'Regime', definition: 'Transitional / mixed tape where signals conflict and position sizes should stay smaller.', learnMorePath: '/about/nowcast' },
  { term: 'FRI', category: 'Regime', definition: 'Factor Rotation Index: momentum-led vs value-led leadership signal.', learnMorePath: '/about/regime' },

  { term: 'Appear', category: 'Screener', definition: 'Weighted appearance count across screeners (sum of style_weight × source_weight over hits).' },
  { term: 'Styles', category: 'Screener', definition: 'Weighted distinct style families hit today (sum of each distinct style’s weight).' },
  { term: 'Sources', category: 'Screener', definition: 'Weighted distinct screen sources hit today (sum of each distinct source’s weight).' },
  { term: 'Best %ile', category: 'Screener', definition: 'Best percentile rank achieved within any style (0% is top, 100% is worst); lower is better.' },
  { term: 'Consensus', category: 'Screener', definition: '0-100 composite that blends coverage and placement with decay-based Long/Short/Net scores, then clips to [0,100].' },
  { term: 'Primary', category: 'Screener', definition: 'Most influential style / screener hit for the day.' },

  { term: UI_TERMS.aiTargets, category: 'AI', definition: 'Model price targets with bull/base/bear scenarios and probabilities.' },
  { term: 'Setup hits', category: 'Screener', definition: 'Number of active screener setups over the selected window.' },
]

export function GlossaryDrawer({
  className,
  renderButton = true,
  renderDialog = true,
}: {
  className?: string
  renderButton?: boolean
  renderDialog?: boolean
}) {
  const glossary = useGlossary()
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (!glossary.isOpen) setQuery('')
  }, [glossary.isOpen])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const term = (glossary.term || '').trim().toLowerCase()
    const items = GLOSSARY
    if (!q && !term) return items
    return items.filter((it) => {
      if (term && it.term.toLowerCase() === term) return true
      if (!q) return false
      return (
        it.term.toLowerCase().includes(q) ||
        it.definition.toLowerCase().includes(q) ||
        it.category.toLowerCase().includes(q)
      )
    })
  }, [query, glossary.term])

  const grouped = useMemo(() => {
    const map = new Map<GlossaryItem['category'], GlossaryItem[]>()
    filtered.forEach((it) => {
      if (!map.has(it.category)) map.set(it.category, [])
      map.get(it.category)!.push(it)
    })
    const categories: GlossaryItem['category'][] = [
      'Liquidity',
      'Funding',
      'Credit',
      'Volatility',
      'Rates & FX',
      'Breadth',
      'Structure',
      'Regime',
      'Screener',
      'AI',
    ]
    return categories
      .filter((c) => map.has(c))
      .map((c) => ({ category: c, items: map.get(c)! }))
  }, [filtered])

  return (
    <>
      {renderButton ? (
        <TooltipCopy tooltipKey="global.glossary">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn(
              'h-8 gap-2 rounded-full px-2 text-xs text-muted-foreground hover:bg-secondary/40 hover:text-foreground',
              className,
            )}
            onClick={() => glossary.open(null)}
            aria-label="Open glossary"
          >
            <BookOpenIcon className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Glossary</span>
          </Button>
        </TooltipCopy>
      ) : null}

      {renderDialog ? (
        <Dialog open={glossary.isOpen} onOpenChange={(next) => (!next ? glossary.close() : null)}>
          <DialogContent
            className={cn(
              'fixed inset-0 left-0 top-0 z-50 grid h-[100dvh] w-screen max-w-none translate-x-0 translate-y-0 grid-rows-[auto_minmax(0,1fr)] gap-0 rounded-none border-0 bg-background p-0',
              'lg:inset-auto lg:right-4 lg:top-16 lg:h-auto lg:max-h-[calc(100dvh-6rem)] lg:w-[460px] lg:max-w-[min(460px,calc(100vw-2rem))] lg:rounded-2xl lg:border lg:p-0',
            )}
            hideClose
          >
            <DialogHeader className="flex flex-row items-center justify-between border-b border-border/60 px-4 py-3">
              <DialogTitle className="flex items-center gap-2 text-base">
                <BookOpenIcon className="h-4 w-4" aria-hidden />
                Glossary
              </DialogTitle>
              <IconButton
                label="Close glossary"
                variant="ghost"
                className="border border-outline/10"
                onClick={() => glossary.close()}
              >
                <XIcon className="h-4 w-4" aria-hidden />
              </IconButton>
            </DialogHeader>

            <div className="min-h-0 overflow-y-auto overscroll-contain px-4 py-4">
              <div className="rounded-2xl border border-outline/10 bg-secondary/10 p-3">
                <div className="flex items-center gap-2">
                  <SearchIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search terms…"
                    aria-label="Search glossary"
                    className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  Short, consistent definitions for dashboard acronyms.
                </div>
              </div>

              <div className="mt-4 space-y-5">
                {grouped.map((g) => (
                  <section key={g.category} aria-label={g.category}>
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{g.category}</div>
                    <div className="mt-2 space-y-2">
                      {g.items.map((it) => (
                        <div key={it.term} className="rounded-xl border border-outline/10 bg-card p-3">
                          <div className="flex items-baseline justify-between gap-3">
                            <div className="font-semibold text-foreground">{it.term}</div>
                            <div className="text-[11px] text-muted-foreground">{it.category}</div>
                          </div>
                          <div className="mt-1 text-sm text-muted-foreground">{it.definition}</div>
                        </div>
                      ))}
                    </div>
                  </section>
                ))}

                {grouped.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-outline/12 bg-secondary/10 p-4 text-sm text-muted-foreground">
                    No matches.
                  </div>
                ) : null}
              </div>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  )
}

export function glossaryDefinition(term: string): string | null {
  const t = (term || '').trim().toLowerCase()
  if (!t) return null
  const found = GLOSSARY.find((it) => it.term.toLowerCase() === t)
  return found?.definition ?? null
}

export function glossaryEntry(term: string): GlossaryItem | null {
  const t = (term || '').trim().toLowerCase()
  if (!t) return null
  return GLOSSARY.find((it) => it.term.toLowerCase() === t) ?? null
}
