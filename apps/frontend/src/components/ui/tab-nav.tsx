import type { AnchorHTMLAttributes, ComponentProps, ReactNode } from 'react'

import Link from 'next/link'

import { cn } from '@/lib/utils'

export function TabNav({
  children,
  className,
  ...props
}: {
  children: ReactNode
  className?: string
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <nav className={cn('tab-nav', className)} {...props}>
      {children}
    </nav>
  )
}

export function tabPillClassName(active?: boolean, className?: string) {
  return cn('tab-pill', active && 'is-active', className)
}

export function TabLink({
  active,
  className,
  ...props
}: {
  active?: boolean
  className?: string
} & Omit<ComponentProps<typeof Link>, 'className'>) {
  return <Link className={tabPillClassName(active, className)} {...props} />
}

export function TabAnchor({
  active,
  className,
  ...props
}: {
  active?: boolean
  className?: string
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'className'>) {
  return <a className={tabPillClassName(active, className)} {...props} />
}
