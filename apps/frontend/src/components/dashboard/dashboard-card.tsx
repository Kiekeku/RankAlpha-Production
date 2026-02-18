import type * as React from 'react'

import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export type DashboardCardProps = {
  title: React.ReactNode
  titleAccessory?: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  children?: React.ReactNode
  className?: string
  headerClassName?: string
  titleClassName?: string
  contentClassName?: string
}

export function DashboardCard({
  title,
  titleAccessory,
  description,
  actions,
  children,
  className,
  headerClassName,
  titleClassName,
  contentClassName,
}: DashboardCardProps) {
  return (
    <Card className={cn('border-outline/8', className)}>
      <CardHeader className={cn('pb-ds-3', headerClassName)}>
        <div className="flex flex-col gap-ds-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-ds-2">
              <h3 className={cn('truncate text-ds-md font-semibold leading-tight tracking-tight', titleClassName)}>
                {title}
              </h3>
              {titleAccessory ? <div className="shrink-0">{titleAccessory}</div> : null}
            </div>
            {description ? (
              <div className="mt-ds-1 text-ds-sm text-muted-foreground">{description}</div>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-ds-2">{actions}</div> : null}
        </div>
      </CardHeader>
      {children ? <CardContent className={cn('space-y-ds-4', contentClassName)}>{children}</CardContent> : null}
    </Card>
  )
}

