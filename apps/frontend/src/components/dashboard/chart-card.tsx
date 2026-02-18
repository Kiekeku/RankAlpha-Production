import type * as React from 'react'

import { DashboardCard, type DashboardCardProps } from '@/components/dashboard/dashboard-card'
import { cn } from '@/lib/utils'

export type ChartCardProps = DashboardCardProps & {
  children: React.ReactNode
}

export function ChartCard({ contentClassName, ...props }: ChartCardProps) {
  return <DashboardCard {...props} contentClassName={cn('space-y-ds-3', contentClassName)} />
}

