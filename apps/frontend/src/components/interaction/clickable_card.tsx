'use client'

import * as React from 'react'

import { Card, type CardProps } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export type ClickableCardProps = Omit<CardProps, 'interactive' | 'onClick'> & {
  onActivate: () => void
  disabled?: boolean
}

export function ClickableCard({
  onActivate,
  disabled,
  className,
  children,
  ...props
}: ClickableCardProps) {
  const toggleCardCheckbox = (card: HTMLElement) => {
    const checkbox = card.querySelector<HTMLInputElement>('input[type="checkbox"]')
    if (!checkbox || checkbox.disabled) return false
    checkbox.click()
    return true
  }
  const onKeyDown = disabled
    ? undefined
    : (event: React.KeyboardEvent) => {
        if (event.target !== event.currentTarget) return
        if (event.repeat) return

        if (event.key === 'Enter') {
          event.preventDefault()
          onActivate()
          return
        }

        if (event.key === ' ' || event.key === 'Spacebar') {
          // Prevent page scroll; activate on keyup to match button behavior.
          event.preventDefault()
          return
        }
      }

  const onKeyUp = disabled
    ? undefined
    : (event: React.KeyboardEvent) => {
        if (event.target !== event.currentTarget) return
        if (event.key === ' ' || event.key === 'Spacebar') {
          event.preventDefault()
          const card = event.currentTarget as HTMLElement
          if (!toggleCardCheckbox(card)) {
            onActivate()
          }
        }
      }

  return (
    <Card
      interactive={!disabled}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled ? true : undefined}
      onClick={disabled ? undefined : onActivate}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      className={cn(
        disabled && 'cursor-not-allowed opacity-60',
        !disabled &&
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        className,
      )}
      {...props}
    >
      {children}
    </Card>
  )
}
