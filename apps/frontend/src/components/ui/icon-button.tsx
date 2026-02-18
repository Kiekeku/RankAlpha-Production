import type { ReactNode } from 'react'

import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function IconButton({
  label,
  className,
  size = 'icon',
  variant = 'outline',
  children,
  ...props
}: {
  label: string
  children: ReactNode
} & Omit<ButtonProps, 'size' | 'variant' | 'children'> &
  Pick<ButtonProps, 'size' | 'variant'>) {
  const sizeClass = size === 'sm' ? 'h-9 w-9' : size === 'lg' ? 'h-12 w-12' : 'h-11 w-11'
  return (
    <Button
      aria-label={label}
      size={size}
      variant={variant}
      className={cn('rounded-full', sizeClass, className)}
      {...props}
    >
      {children}
    </Button>
  )
}
