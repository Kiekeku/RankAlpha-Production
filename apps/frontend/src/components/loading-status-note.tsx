'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

import { cn } from '@/lib/utils'

export function LoadingStatusNote({
  label,
  statusHref = '/about/pipeline',
  delayMs = 2000,
  className,
  showLabel = true,
}: {
  label: string
  statusHref?: string
  delayMs?: number
  className?: string
  showLabel?: boolean
}) {
  const [showSlow, setShowSlow] = useState(false)

  useEffect(() => {
    setShowSlow(false)
    const t = window.setTimeout(() => setShowSlow(true), delayMs)
    return () => window.clearTimeout(t)
  }, [delayMs])

  return (
    <div className={cn('text-xs text-muted-foreground', className)}>
      {showLabel ? (
        <div className="text-sm font-medium text-foreground">{label}</div>
      ) : null}
      {showSlow ? (
        <div className="mt-1 text-xs text-muted-foreground">
          Still loading—data source may be degraded.{' '}
          <Link href={statusHref} className="font-semibold text-primary hover:underline">
            Data Status
          </Link>
        </div>
      ) : null}
    </div>
  )
}
