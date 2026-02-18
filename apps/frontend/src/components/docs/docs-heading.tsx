'use client'

import type { ReactNode } from 'react'

import Link from 'next/link'
import { LinkIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

export function DocsHeading({
  id,
  level = 2,
  className,
  children,
}: {
  id: string
  level?: 2 | 3 | 4
  className?: string
  children: ReactNode
}) {
  const Tag = level === 2 ? 'h2' : level === 3 ? 'h3' : 'h4'
  return (
    <Tag id={id} className={cn('group scroll-mt-24 font-semibold text-foreground', className)}>
      <span>{children}</span>
      <Link
        href={`#${id}`}
        aria-label={`Link to ${id} section`}
        className="ml-2 inline-flex items-center text-muted-foreground opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100"
      >
        <LinkIcon className="h-3.5 w-3.5" />
      </Link>
    </Tag>
  )
}
