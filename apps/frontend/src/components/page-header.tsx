import { Fragment, type ReactNode } from 'react'

import { cn } from '@/lib/utils'

type PageHeaderProps = {
  title: ReactNode
  subtitle?: string
  contextBadges?: ReactNode[]
  titleAddon?: ReactNode
  primaryAction?: ReactNode
  secondaryActions?: ReactNode[]
  tabs?: ReactNode
  activeChips?: ReactNode
  className?: string
}

export function PageHeader({
  title,
  subtitle,
  contextBadges,
  titleAddon,
  primaryAction,
  secondaryActions,
  tabs,
  activeChips,
  className,
}: PageHeaderProps) {
  const context = (contextBadges || []).filter(Boolean)
  const secondary = (secondaryActions || []).filter(Boolean)

  return (
    <section className={cn('space-y-3 sm:space-y-4', className)}>
      <div className="rounded-2xl border border-outline/10 bg-card px-4 py-4 sm:px-6 sm:py-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold leading-tight md:text-3xl">{title}</h1>
              {titleAddon}
            </div>
            {subtitle ? (
              <p className="text-[15px] text-muted-foreground sm:text-base">
                {subtitle}
              </p>
            ) : null}
            {context.length ? (
              <div className="flex flex-wrap items-center text-xs text-muted-foreground">
                {context.map((item, index) => (
                  <Fragment key={index}>
                    {index > 0 ? <span className="mx-2 text-muted-foreground/70">-</span> : null}
                    <span className="inline-flex items-center gap-1">{item}</span>
                  </Fragment>
                ))}
              </div>
            ) : null}
          </div>
          {primaryAction || secondary.length ? (
            <div className="flex flex-col items-start gap-2 sm:items-end">
              {primaryAction}
              {secondary.length ? (
                <div className="flex flex-wrap items-center gap-2">
                  {secondary.map((action, index) => (
                    <Fragment key={index}>{action}</Fragment>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {tabs ? <div>{tabs}</div> : null}
      {activeChips ? <div>{activeChips}</div> : null}
    </section>
  )
}
