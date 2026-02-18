'use client'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { glossaryDefinition } from '@/components/glossary/glossary_drawer'
import { useGlossary } from '@/components/glossary/glossary_context'

export function Acronym({
  term,
  definition,
  showIcon = false,
  className,
}: {
  term: string
  definition?: string
  showIcon?: boolean
  className?: string
}) {
  const glossary = useGlossary()
  const def = definition ?? glossaryDefinition(term) ?? ''
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
          {term}
          {showIcon ? <span className="text-muted-foreground">↗</span> : null}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm px-3 py-2 text-xs leading-relaxed">
        {def || 'Open glossary for definition.'}
      </TooltipContent>
    </Tooltip>
  )
}
