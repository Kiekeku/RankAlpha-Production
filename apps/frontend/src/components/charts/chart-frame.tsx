import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export function ChartFrame({
  header,
  children,
  className,
  contentClassName,
}: {
  header?: ReactNode
  children: ReactNode
  className?: string
  contentClassName?: string
}) {
  return (
    <div className={cn('rounded-xl border border-outline/10 bg-background px-3 py-3', className)}>
      {header ? <div className="mb-3">{header}</div> : null}
      <div className={cn('min-w-0', contentClassName)}>{children}</div>
    </div>
  )
}
