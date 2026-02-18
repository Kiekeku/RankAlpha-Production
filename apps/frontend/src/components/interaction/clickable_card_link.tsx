import type * as React from 'react'
import Link from 'next/link'

import { Card, type CardProps } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export type ClickableCardLinkProps = Omit<CardProps, 'interactive'> & {
  href: string
  ariaLabel?: string
  linkClassName?: string
  prefetch?: boolean
}

export function ClickableCardLink({
  href,
  ariaLabel,
  linkClassName,
  className,
  children,
  prefetch,
  ...props
}: ClickableCardLinkProps) {
  return (
    <Link href={href} aria-label={ariaLabel} className={cn('block', linkClassName)} prefetch={prefetch}>
      <Card interactive className={className} {...props}>
        {children}
      </Card>
    </Link>
  )
}

