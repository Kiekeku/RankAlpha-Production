'use client'

import Link from 'next/link'
import { BookTextIcon, ExternalLinkIcon, XIcon } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { cn } from '@/lib/utils'
import { useFactors } from '@/components/factors/factors_context'
import { FactorMethodologyContent } from '@/components/factors/factor_methodology_content'

export function FactorsDrawer({
  className,
  renderDialog = true,
}: {
  className?: string
  renderDialog?: boolean
}) {
  const factors = useFactors()

  return (
    <>
      {renderDialog ? (
        <Dialog open={factors.isOpen} onOpenChange={(next) => (!next ? factors.close() : null)}>
        <DialogContent
          className={cn(
            'fixed inset-0 left-0 top-0 z-50 grid h-[100dvh] w-screen max-w-none translate-x-0 translate-y-0 grid-rows-[auto_minmax(0,1fr)] gap-0 rounded-none border-0 bg-background p-0',
            'lg:inset-auto lg:right-4 lg:top-16 lg:h-auto lg:max-h-[calc(100dvh-6rem)] lg:w-[560px] lg:max-w-[min(560px,calc(100vw-2rem))] lg:rounded-2xl lg:border lg:p-0',
            className,
          )}
          hideClose
        >
            <DialogHeader className="flex flex-row items-center justify-between border-b border-border/60 px-4 py-3">
              <div className="min-w-0">
                <DialogTitle className="flex items-center gap-2 text-base">
                  <BookTextIcon className="h-4 w-4" aria-hidden />
                  Methodology
                </DialogTitle>
                <div className="mt-1 text-xs text-muted-foreground">How Momentum, Value, and Sentiment feed grades.</div>
              </div>
              <div className="flex items-center gap-2">
                <Link
                  href="/methodology#factors"
                  onClick={() => factors.close()}
                  className="inline-flex h-9 items-center rounded-full border border-outline/10 bg-card px-3 text-xs font-semibold text-muted-foreground transition hover:border-outline/16 hover:text-foreground"
                >
                  Open full page
                  <ExternalLinkIcon className="ml-2 h-4 w-4" aria-hidden />
                </Link>
                <IconButton
                  label="Close methodology"
                  variant="ghost"
                  className="border border-outline/10"
                  onClick={() => factors.close()}
                >
                  <XIcon className="h-4 w-4" aria-hidden />
                </IconButton>
              </div>
            </DialogHeader>

            <div className="min-h-0 overflow-y-auto overscroll-contain px-4 py-4">
              <FactorMethodologyContent />
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  )
}
