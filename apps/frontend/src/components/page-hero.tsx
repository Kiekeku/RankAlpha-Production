import { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export function PageHero(props: {
  title: ReactNode
  subtitle?: string
  right?: ReactNode
  className?: string
  titleAddon?: ReactNode
  meta?: ReactNode
}) {
  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-3xl bg-gradient-to-br from-primary/8 via-card to-card px-3 py-4 shadow-md sm:px-5 sm:py-5 lg:px-6',
        props.className
      )}
    >
      <div className="absolute -left-16 top-12 h-44 w-44 rounded-full bg-primary/10 blur-3xl" aria-hidden="true" />
      <div className="absolute -right-20 -bottom-20 h-64 w-64 rounded-full bg-primary/8 blur-3xl" aria-hidden="true" />

      <div className="relative flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold leading-tight md:text-3xl">{props.title}</h1>
            {props.titleAddon}
          </div>
          {props.subtitle ? <p className="text-sm text-muted-foreground">{props.subtitle}</p> : null}
          {props.meta ? <div>{props.meta}</div> : null}
        </div>
        {props.right ? <div className="flex justify-start sm:justify-end">{props.right}</div> : null}
      </div>
    </section>
  )
}
