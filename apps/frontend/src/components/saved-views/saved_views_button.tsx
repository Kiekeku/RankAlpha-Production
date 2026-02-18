'use client'

import { BookmarkIcon } from 'lucide-react'

import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function SavedViewsButton({
  onClick,
  label = 'Saved views',
  className,
  iconClassName,
  variant = 'outline',
  ...props
}: Omit<ButtonProps, 'children' | 'onClick' | 'variant'> & {
  onClick: () => void
  label?: string
  className?: string
  iconClassName?: string
  variant?: 'outline' | 'ghost'
}) {
  const baseClass =
    variant === 'ghost'
      ? 'h-8 rounded-full px-2 text-xs font-semibold text-muted-foreground hover:bg-secondary/40 hover:text-foreground'
      : 'h-9 rounded-full border-outline/10 bg-card px-4 text-sm font-medium text-muted-foreground hover:border-outline/16 hover:text-foreground'

  return (
    <Button
      type="button"
      variant={variant}
      size="sm"
      className={cn(baseClass, className)}
      onClick={onClick}
      {...props}
    >
      <BookmarkIcon className={cn('mr-1 h-3.5 w-3.5', iconClassName)} aria-hidden />
      {label}
    </Button>
  )
}
