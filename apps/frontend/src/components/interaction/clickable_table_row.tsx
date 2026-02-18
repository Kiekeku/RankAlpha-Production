'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

export type ClickableTableRowProps = React.HTMLAttributes<HTMLTableRowElement> & {
  onActivate: () => void
  selected?: boolean
  disabled?: boolean
}

export function ClickableTableRow({
  onActivate,
  selected,
  disabled,
  className,
  children,
  ...props
}: ClickableTableRowProps) {
  const toggleRowCheckbox = (row: HTMLTableRowElement) => {
    const checkbox = row.querySelector<HTMLInputElement>('input[type="checkbox"]')
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

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault()
          const row = event.currentTarget as HTMLTableRowElement
          const scope = row.closest('tbody') ?? row.parentElement
          if (!scope) return
          const rows = Array.from(scope.querySelectorAll<HTMLTableRowElement>('tr[role=\"button\"]'))
          const idx = rows.indexOf(row)
          if (idx < 0) return
          const nextIdx = event.key === 'ArrowDown' ? idx + 1 : idx - 1
          const next = rows[nextIdx]
          if (next) next.focus()
        }
      }

  const onKeyUp = disabled
    ? undefined
    : (event: React.KeyboardEvent) => {
        if (event.target !== event.currentTarget) return
        if (event.key === ' ' || event.key === 'Spacebar') {
          event.preventDefault()
          const row = event.currentTarget as HTMLTableRowElement
          if (!toggleRowCheckbox(row)) {
            onActivate()
          }
        }
      }

  return (
    <tr
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled ? true : undefined}
      onClick={disabled ? undefined : onActivate}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      className={cn(
        'border-t transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-muted/40',
        selected ? 'bg-secondary/20' : null,
        className,
      )}
      {...props}
    >
      {children}
    </tr>
  )
}
