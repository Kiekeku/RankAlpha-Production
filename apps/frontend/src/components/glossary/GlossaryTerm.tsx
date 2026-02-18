'use client'

import Link from 'next/link'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { glossaryDefinition, glossaryEntry } from '@/components/glossary/glossary_drawer'
import { useGlossary } from '@/components/glossary/glossary_context'

export function GlossaryTerm({
  term,
  label,
  definition,
  learnMoreHref,
  showIcon = false,
  className,
}: {
  term: string
  label?: string
  definition?: string
  learnMoreHref?: string
  showIcon?: boolean
  className?: string
}) {
  const glossary = useGlossary()
  const entry = glossaryEntry(term)
  const def = definition ?? entry?.definition ?? glossaryDefinition(term) ?? ''
  const learnMore = learnMoreHref ?? entry?.learnMorePath
  const text = label ?? term

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            glossary.open(term)
          }}
          className={cn(
            'inline-flex items-center gap-1 font-semibold text-foreground underline decoration-dotted decoration-outline/30 underline-offset-2 hover:decoration-outline/50',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
            className,
          )}
          aria-label={`Define ${term}`}
        >
          {text}
          {showIcon ? <span className="text-muted-foreground">↗</span> : null}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs px-3 py-2 text-xs leading-relaxed">
        <div>{def || 'Open glossary for definition.'}</div>
        {learnMore ? (
          <Link
            href={learnMore}
            className="mt-2 inline-flex text-xs font-semibold text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary"
          >
            Learn more
          </Link>
        ) : null}
      </TooltipContent>
    </Tooltip>
  )
}
