import { cn } from '@/lib/utils'

export function FilterSidebar({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('space-y-4', className)}>
      {children}
    </div>
  )
}

export function FilterGroup({
  title,
  description,
  titleAddon,
  children,
  className,
}: {
  title: string
  description?: string
  titleAddon?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('space-y-2', className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
        {titleAddon}
      </div>
      {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
      <div className="space-y-3">{children}</div>
    </section>
  )
}
