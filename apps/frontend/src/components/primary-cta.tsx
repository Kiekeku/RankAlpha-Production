import type { ButtonHTMLAttributes, ComponentProps, ReactNode } from 'react'

import Link from 'next/link'

import { cn } from '@/lib/utils'

export const primaryCtaClassName =
  'inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm shadow-primary/25 transition hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background'

export function PrimaryCtaLink({
  href,
  className,
  children,
  ...props
}: {
  href: string
  className?: string
  children: ReactNode
} & Omit<ComponentProps<typeof Link>, 'href' | 'className' | 'children'>) {
  return (
    <Link href={href} className={cn(primaryCtaClassName, className)} {...props}>
      {children}
    </Link>
  )
}

export function PrimaryCtaButton({
  className,
  children,
  type = 'button',
  ...props
}: {
  className?: string
  children: ReactNode
  type?: 'button' | 'submit' | 'reset'
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className' | 'children' | 'type'>) {
  return (
    <button type={type} className={cn(primaryCtaClassName, className)} {...props}>
      {children}
    </button>
  )
}
