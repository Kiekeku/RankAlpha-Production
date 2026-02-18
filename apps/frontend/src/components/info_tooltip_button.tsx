'use client'

import { useState } from 'react'
import { Info as InfoIcon } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function InfoTooltip({
  description,
  label,
  iconSize = 'h-4 w-4',
  contentClassName = 'max-w-sm px-ds-3 py-ds-2 text-ds-xs leading-relaxed',
  buttonClassName,
  learnMore,
}: {
  description: React.ReactNode
  label: string
  iconSize?: string
  contentClassName?: string
  buttonClassName?: string
  learnMore?: { label?: string; onClick: () => void }
}) {
  const [open, setOpen] = useState(false)

  return (
    <TooltipProvider>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            className={cn(
              'inline-flex items-center justify-center rounded-md text-muted-foreground transition hover:text-foreground',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              buttonClassName,
            )}
            aria-label={`Explain ${label}`}
            aria-expanded={open}
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              setOpen((prev) => !prev)
            }}
          >
            <InfoIcon className={iconSize} aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent className={contentClassName}>
          <div className="space-y-2">
            <div>{description}</div>
            {learnMore ? (
              <div className="pt-1">
                <button
                  type="button"
                  className="text-xs font-semibold text-primary hover:underline"
                  onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    setOpen(false)
                    learnMore.onClick()
                  }}
                >
                  {learnMore.label ?? 'Learn more'}
                </button>
              </div>
            ) : null}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export function InfoTooltipButton(props: React.ComponentProps<typeof InfoTooltip>) {
  return <InfoTooltip {...props} />
}
