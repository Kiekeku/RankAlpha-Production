'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PrimaryCtaButton } from '@/components/primary-cta'
import { cn } from '@/lib/utils'

const INTRO_DISMISSED_KEY = 'ra_intro_dismissed'

const FOR_CHIPS = ['Retail quants', 'Factor investors', 'Swing traders', 'Data-driven discretionary']

export function AudienceHero({ className }: { className?: string }) {
  const [ready, setReady] = useState(false)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    try {
      const dismissed = window.localStorage.getItem(INTRO_DISMISSED_KEY) === '1'
      setVisible(!dismissed)
    } catch {
      setVisible(true)
    } finally {
      setReady(true)
    }
  }, [])

  const forLabels = useMemo(() => FOR_CHIPS, [])

  const dismiss = () => {
    try {
      window.localStorage.setItem(INTRO_DISMISSED_KEY, '1')
    } catch {
      // ignore
    }
    setVisible(false)
  }

  if (!ready || !visible) return null

  return (
    <section
      className={cn(
        'rounded-3xl border border-outline/12 bg-gradient-to-br from-secondary/20 via-background to-background p-4 shadow-sm sm:p-6',
        className,
      )}
      aria-label="About RankAlpha"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Start here</div>
          <h2 className="text-2xl font-semibold text-foreground sm:text-3xl">
            RankAlpha is a quant research dashboard.
          </h2>
          <p className="max-w-2xl text-sm text-muted-foreground sm:text-base">
            Factor grades + screeners + compare + AI memos to help triage and investigate. 
          </p>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">For</span>
              {forLabels.map((label) => (
                <Badge key={label} variant="secondary" className="px-2.5 py-1 text-[11px]">
                  {label}
                </Badge>
              ))}
            </div>
            <div className="text-xs text-muted-foreground">
              Not for: latest news, real-time data, high-frequency trading.
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PrimaryCtaButton className="h-9 rounded-full px-4 text-xs sm:text-sm" onClick={dismiss}>
            Enter the app
          </PrimaryCtaButton>
          <Link
            href="/about"
            className="inline-flex h-9 items-center justify-center rounded-full border border-input bg-background px-4 text-xs font-medium text-foreground transition hover:bg-accent hover:text-accent-foreground sm:text-sm"
          >
            Methodology
          </Link>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-9 rounded-full px-3 text-xs text-muted-foreground hover:text-foreground"
            onClick={dismiss}
          >
            Dismiss
          </Button>
        </div>
      </div>
    </section>
  )
}
