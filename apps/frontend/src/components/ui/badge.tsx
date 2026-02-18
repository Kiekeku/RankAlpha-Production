import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold leading-none transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-primary text-primary-foreground',
        secondary:
          'border-transparent bg-secondary text-secondary-foreground',
        destructive:
          'border-transparent bg-destructive text-destructive-foreground',
        outline: 'border-outline/18 bg-transparent text-foreground',
        success:
          'border-status-success/25 bg-status-success/10 text-status-success dark:bg-status-success/12',
        danger:
          'border-status-danger/25 bg-status-danger/10 text-status-danger dark:bg-status-danger/12',
        warning:
          'border-status-warning/25 bg-status-warning/10 text-status-warning-foreground',
        info:
          'border-status-info/25 bg-status-info/10 text-status-info-foreground',
        model:
          'border-status-model/25 bg-status-model/10 text-status-model-foreground',
      },
      interactive: {
        false: 'cursor-default select-none',
        true: 'cursor-pointer select-none hover:border-outline/28',
      },
    },
    compoundVariants: [
      { variant: 'default', interactive: true, className: 'hover:bg-primary/80' },
      { variant: 'secondary', interactive: true, className: 'hover:bg-secondary/80' },
      { variant: 'destructive', interactive: true, className: 'hover:bg-destructive/80' },
      { variant: 'outline', interactive: true, className: 'hover:bg-accent hover:text-accent-foreground' },
      {
        variant: 'success',
        interactive: true,
        className: 'hover:bg-status-success/15 dark:hover:bg-status-success/16',
      },
      {
        variant: 'danger',
        interactive: true,
        className: 'hover:bg-status-danger/15 dark:hover:bg-status-danger/16',
      },
      { variant: 'warning', interactive: true, className: 'hover:bg-status-warning/15' },
      { variant: 'info', interactive: true, className: 'hover:bg-status-info/15' },
      { variant: 'model', interactive: true, className: 'hover:bg-status-model/15' },
    ],
    defaultVariants: {
      variant: 'default',
      interactive: false,
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, interactive, ...props }, ref) => (
    <span ref={ref} className={cn(badgeVariants({ variant, interactive }), className)} {...props} />
  )
)
Badge.displayName = 'Badge'

export { Badge, badgeVariants }
