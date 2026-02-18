'use client'

import { useEffect, useRef } from 'react'
import { AlertTriangleIcon, InboxIcon, RefreshCcwIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { emitTelemetry } from '@/lib/telemetry'
import { Skeleton } from '@/components/ui/skeleton'
import { LoadingStatusNote } from '@/components/loading-status-note'

type FilterChip = {
  key?: string
  label: string
  onRemove?: () => void
}

type Action = {
  label: string
  onClick: () => void
  variant?: 'default' | 'outline'
}

type DataStateWrapperProps = {
  status: 'loading' | 'empty' | 'error' | 'ready'
  title?: string
  message?: string
  loadingLabel?: string
  lastUpdated?: string | null
  filters?: FilterChip[]
  clearFiltersLabel?: string
  onClearFilters?: () => void
  onRetry?: () => void
  statusHref?: string
  statusLabel?: string
  tips?: string[]
  primaryAction?: Action
  secondaryAction?: Action
  actions?: Action[]
  error?: unknown
  context?: string
  size?: 'default' | 'compact'
  className?: string
  children?: React.ReactNode
}

function openStatusLink(href: string) {
  if (typeof window === 'undefined') return
  window.open(href, '_blank', 'noopener,noreferrer')
}

export function DataStateWrapper({
  status,
  title,
  message,
  loadingLabel,
  lastUpdated,
  filters,
  clearFiltersLabel = 'Clear all filters',
  onClearFilters,
  onRetry,
  statusHref,
  statusLabel = 'Status',
  tips,
  primaryAction,
  secondaryAction,
  actions,
  error,
  context,
  size = 'default',
  className,
  children,
}: DataStateWrapperProps) {
  const lastErrorKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (status !== 'error') return
    const detail = {
      event: 'data_state_error',
      context: context || 'unknown',
      message: message || 'Data temporarily unavailable',
      error: error ? String(error) : undefined,
    }
    const key = `${detail.context}:${detail.message}:${detail.error ?? ''}`
    if (lastErrorKeyRef.current === key) return
    lastErrorKeyRef.current = key
    // eslint-disable-next-line no-console
    console.error('[DataStateWrapper]', detail)
    emitTelemetry(detail)
  }, [status, context, message, error])

  if (status === 'ready') {
    return <>{children}</>
  }

  const isCompact = size === 'compact'
  const padding = isCompact ? 'p-4' : 'p-6'
  const titleClass = isCompact ? 'text-sm' : 'text-base'
  const descClass = isCompact ? 'text-xs' : 'text-sm'
  const iconWrap = isCompact ? 'h-9 w-9' : 'h-12 w-12'
  const iconSize = isCompact ? 'h-4 w-4' : 'h-5 w-5'

  if (status === 'loading') {
    const loadingText = loadingLabel || title || 'Loading data…'
    const statusLink = statusHref || '/about/pipeline'
    return (
      <div
        className={cn(
          'rounded-2xl border border-primary/20 bg-primary/5 text-center',
          padding,
          className,
        )}
      >
        <div className="mx-auto mb-3 flex items-center justify-center">
          <Skeleton className={cn('rounded-full', iconWrap)} />
        </div>
        <div className="flex flex-col items-center gap-2">
          <Skeleton className={cn('h-4 w-32', isCompact && 'h-3 w-24')} />
          <Skeleton className={cn('h-3 w-48', isCompact && 'h-2.5 w-40')} />
        </div>
        <LoadingStatusNote
          label={loadingText}
          statusHref={statusLink}
          className={cn('mt-3', descClass)}
          showLabel
        />
        {lastUpdated ? (
          <div className={cn('mt-2 text-xs text-muted-foreground', isCompact ? '' : 'uppercase tracking-wide')}>
            Last updated: {lastUpdated}
          </div>
        ) : null}
      </div>
    )
  }

  if (status === 'error') {
    const handleRetry = onRetry
      ? onRetry
      : () => {
          if (typeof window === 'undefined') return
          window.location.reload()
        }

    return (
      <div
        className={cn(
          'rounded-2xl border border-destructive/30 bg-destructive/5 text-center',
          padding,
          className,
        )}
      >
        <div className="mx-auto mb-3 flex items-center justify-center rounded-full border border-destructive/30 bg-destructive/10 text-destructive">
          <div className={cn('flex items-center justify-center', iconWrap)}>
            <AlertTriangleIcon className={cn(iconSize)} aria-hidden />
          </div>
        </div>
        <div className={cn('font-semibold text-destructive', titleClass)}>{title || "Couldn't load data."}</div>
        <div className={cn('mt-1 text-muted-foreground', descClass)}>
          {message || 'Please try again.'}
        </div>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-full px-4"
            onClick={handleRetry}
          >
            <RefreshCcwIcon className="mr-1 h-4 w-4" aria-hidden />
            Retry
          </Button>
          {statusHref ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-full px-4"
              onClick={() => openStatusLink(statusHref)}
            >
              {statusLabel}
            </Button>
          ) : null}
        </div>
      </div>
    )
  }

  const hasFilters = Boolean(filters && filters.length > 0)
  const showClearFilters = Boolean(onClearFilters && hasFilters)

  const actionItems = actions && actions.length
    ? actions
    : [primaryAction, secondaryAction].filter(Boolean) as Action[]

  return (
    <div
      className={cn(
        'rounded-2xl border border-dashed border-outline/16 bg-card text-center',
        padding,
        className,
      )}
    >
      <div className="mx-auto mb-3 flex items-center justify-center rounded-full border border-outline/16 bg-secondary/10 text-muted-foreground">
        <div className={cn('flex items-center justify-center', iconWrap)}>
          <InboxIcon className={cn(iconSize)} aria-hidden />
        </div>
      </div>
      <div className={cn('font-semibold text-foreground', titleClass)}>{title || 'No results'}</div>
      <div className={cn('mt-1 text-muted-foreground', descClass)}>
        {message || 'We could not find anything that matches your filters.'}
      </div>

      {hasFilters ? (
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {(filters || []).map((chip, idx) => (
            <span
              key={chip.key || `${chip.label}-${idx}`}
              className="inline-flex items-center gap-1 rounded-full border border-outline/10 bg-card px-3 py-1 text-[11px] font-semibold text-muted-foreground"
            >
              <span>{chip.label}</span>
              {chip.onRemove ? (
                <button
                  type="button"
                  className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground transition hover:bg-secondary/20 hover:text-foreground"
                  onClick={chip.onRemove}
                  aria-label={`Remove filter ${chip.label}`}
                >
                  ×
                </button>
              ) : null}
            </span>
          ))}
        </div>
      ) : null}

      {tips && tips.length ? (
        <div className="mt-4 rounded-xl border border-outline/10 bg-secondary/10 p-3 text-left">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Tips</div>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {tips.map((tip, idx) => (
              <li key={`${tip}-${idx}`}>• {tip}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {showClearFilters ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-full px-4"
            onClick={onClearFilters}
          >
            {clearFiltersLabel}
          </Button>
        ) : null}
        {actionItems.map((action) => (
          <Button
            key={action.label}
            type="button"
            variant={action.variant ?? 'outline'}
            size="sm"
            className="h-9 rounded-full px-4"
            onClick={action.onClick}
          >
            {action.label}
          </Button>
        ))}
      </div>
    </div>
  )
}
