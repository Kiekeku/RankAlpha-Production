'use client'

import { useEffect, useMemo } from 'react'
import { BookTextIcon, XIcon } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { cn } from '@/lib/utils'
import { useMethodology } from '@/components/methodology/methodology_context'
import { TooltipCopy } from '@/components/tooltip_copy'

type SectionItem = {
  id: string
  title: string
  summary: string
  bullets: string[]
}

const SECTIONS: SectionItem[] = [
  {
    id: 'nowcast',
    title: 'Risk Nowcast',
    summary: 'A fast read on whether conditions are risk-on, mixed, or risk-off.',
    bullets: [
      'Combines multiple pillars (liquidity, funding/credit stress, and volatility) into a 0-100 risk-off score.',
      'Pillars are normalized so heterogeneous inputs can be compared on a common scale.',
      'The headline label is a rule-based mapping from the composite score and recent changes.',
    ],
  },
  {
    id: 'liquidity',
    title: 'Liquidity',
    summary: 'System liquidity and policy plumbing that can amplify or dampen risk-taking.',
    bullets: [
      'ON RRP and TGA capture key cash drainage and absorption channels.',
      'Net Liquidity is a proxy that combines multiple balance-sheet components into one signal.',
      'We focus on direction and regime classification rather than a single magic threshold.',
    ],
  },
  {
    id: 'funding',
    title: 'Funding Stress',
    summary: 'Short-term funding pressure that tends to surface before broader risk-off moves.',
    bullets: [
      'FRA-OIS is a classic funding stress spread (forward minus OIS).',
      'The regime label is derived from a z-score on a long window for consistency.',
      'We treat it as a stress thermometer, not a timing tool by itself.',
    ],
  },
  {
    id: 'credit',
    title: 'Credit Stress',
    summary: 'Credit spreads as a real economy and balance-sheet pressure gauge.',
    bullets: [
      'HY OAS widens when risk appetite deteriorates and default risk reprices.',
      'We show both the raw level context and a smoothed/z-scored stress view.',
      'The label reflects how extreme the current level is versus history.',
    ],
  },
  {
    id: 'volatility',
    title: 'Volatility Regime',
    summary: 'Implied vol, term structure, and volatility risk premium signals.',
    bullets: [
      'VIX level plus term structure provides a quick read on risk pricing.',
      'VRP (implied minus realized) reflects how expensive protection is versus realized moves.',
      'Flags like contango/backwardation help contextualize the regime.',
    ],
  },
  {
    id: 'rates-fx',
    title: 'Rates and USD',
    summary: 'Cost of capital and dollar strength as tightening channels.',
    bullets: [
      '10Y yields and Fed Funds (O/N) summarize the rate backdrop.',
      '2s10s slope helps contextualize curve dynamics.',
      'USDX captures broad USD strength which can pressure risk assets and global liquidity.',
      'TIPS real yields provide a real-rate lens on financial conditions.',
    ],
  },
  {
    id: 'breadth',
    title: 'Breadth and Flows',
    summary: 'Participation and positioning proxies behind index-level moves.',
    bullets: [
      'Breadth measures how widely participation is distributed beyond a handful of names.',
      'A/D ratio provides a simple advancers vs decliners context read.',
      'Money flow summarizes cyclical minus defensive leadership as a risk appetite proxy.',
    ],
  },
  {
    id: 'cross-asset',
    title: 'Cross-Asset Radar',
    summary: 'Context-only read across duration, real rates, commodities, EM risk, and key FX.',
    bullets: [
      'Not a core nowcast input, but useful for spotting divergence and global risk tone.',
      'Think of it as a quick dashboard for consistency checks across markets.',
    ],
  },
]

export function MethodologyDrawer({
  className,
  renderButton = true,
  renderDialog = true,
}: {
  className?: string
  renderButton?: boolean
  renderDialog?: boolean
}) {
  const methodology = useMethodology()

  const active = useMemo(() => {
    const s = (methodology.section || '').trim().toLowerCase()
    if (!s) return null
    return SECTIONS.find((it) => it.id.toLowerCase() === s) ?? null
  }, [methodology.section])

  useEffect(() => {
    if (!methodology.isOpen) return
    const target = methodology.section ? `methodology-${methodology.section}` : null
    if (!target) return
    const raf = requestAnimationFrame(() => {
      const el = document.getElementById(target)
      if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' })
    })
    return () => cancelAnimationFrame(raf)
  }, [methodology.isOpen, methodology.section])

  return (
    <>
      {renderButton ? (
        <TooltipCopy tooltipKey="global.methodology">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn(
              'h-8 gap-2 rounded-full px-2 text-xs text-muted-foreground hover:bg-secondary/40 hover:text-foreground',
              className,
            )}
            onClick={() => methodology.open(null)}
            aria-label="Open methodology"
          >
            <BookTextIcon className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Methodology</span>
          </Button>
        </TooltipCopy>
      ) : null}

      {renderDialog ? (
        <Dialog open={methodology.isOpen} onOpenChange={(next) => (!next ? methodology.close() : null)}>
          <DialogContent
            className={cn(
              'fixed inset-0 left-0 top-0 z-50 grid h-[100dvh] w-screen max-w-none translate-x-0 translate-y-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-0 rounded-none border-0 bg-background p-0',
              'lg:inset-auto lg:right-4 lg:top-16 lg:h-auto lg:max-h-[calc(100dvh-6rem)] lg:w-[520px] lg:max-w-[min(520px,calc(100vw-2rem))] lg:rounded-2xl lg:border lg:p-0',
            )}
            hideClose
          >
            <DialogHeader className="flex flex-row items-center justify-between border-b border-border/60 px-4 py-3">
              <div className="min-w-0">
                <DialogTitle className="flex items-center gap-2 text-base">
                  <BookTextIcon className="h-4 w-4" aria-hidden />
                  Methodology
                </DialogTitle>
                <div className="mt-1 text-xs text-muted-foreground">
                  How to read the Overview dashboard, without leaving the page.
                </div>
              </div>
              <IconButton
                label="Close methodology"
                variant="ghost"
                className="border border-outline/10"
                onClick={() => methodology.close()}
              >
                <XIcon className="h-4 w-4" aria-hidden />
              </IconButton>
            </DialogHeader>

            <div className="border-b border-border/60 px-4 py-3">
              <div className="flex flex-wrap gap-2">
                {SECTIONS.map((s) => {
                  const isActive = active?.id === s.id
                  return (
                    <Button
                      key={s.id}
                      type="button"
                      size="sm"
                      variant={isActive ? 'default' : 'outline'}
                      className="h-8 rounded-full px-3 text-xs"
                      onClick={() => methodology.open(s.id)}
                    >
                      {s.title}
                    </Button>
                  )
                })}
              </div>
            </div>

            <div className="min-h-0 overflow-y-auto overscroll-contain px-4 py-4">
              <div className="space-y-5">
                {SECTIONS.map((s) => (
                  <section key={s.id} id={`methodology-${s.id}`} aria-label={s.title}>
                    <div className="rounded-2xl border border-outline/10 bg-card p-4">
                      <div className="text-sm font-semibold text-foreground">{s.title}</div>
                      <div className="mt-1 text-sm text-muted-foreground">{s.summary}</div>
                      <ul className="mt-3 list-disc space-y-1 pl-4 text-sm text-muted-foreground">
                        {s.bullets.map((b) => (
                          <li key={b}>{b}</li>
                        ))}
                      </ul>
                    </div>
                  </section>
                ))}
              </div>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  )
}
