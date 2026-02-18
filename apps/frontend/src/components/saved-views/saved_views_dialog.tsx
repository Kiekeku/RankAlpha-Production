'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/use-toast'
import { createSavedView, readSavedViews, writeSavedViews, type SavedView } from '@/lib/saved_views'
import { useSession } from 'next-auth/react'

type SavedViewsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  storageKey: string
  title?: string
  namePlaceholder?: string
  helperText?: string
  maxViews?: number
  currentQuery: string
  buildUrlForQuery: (query: string) => string
  buildUrlForView?: (view: SavedView) => string
  onLoad: (view: SavedView) => void
  showCopyCurrentLink?: boolean
  showCopyPerView?: boolean
  showQueryPreview?: boolean
  showSavedAt?: boolean
  savePath?: string
}

export function SavedViewsDialog({
  open,
  onOpenChange,
  storageKey,
  title = 'Saved views',
  namePlaceholder = 'e.g., My daily triage',
  helperText = 'Saved Views store the current URL filters so you can return to the same screen later.',
  maxViews = 25,
  currentQuery,
  buildUrlForQuery,
  buildUrlForView,
  onLoad,
  showCopyCurrentLink = true,
  showCopyPerView = true,
  showQueryPreview = true,
  showSavedAt = false,
  savePath,
}: SavedViewsDialogProps) {
  const { toast } = useToast()
  const { data: session } = useSession()
  const isSignedIn = Boolean(session?.user)
  const [viewName, setViewName] = useState('')
  const [savedViews, setSavedViews] = useState<SavedView[]>([])
  const trimmedName = viewName.trim()
  const nameIsValid = trimmedName.length >= 2
  const showNameError = trimmedName.length > 0 && !nameIsValid

  const syncSavedViews = useCallback(() => {
    const views = readSavedViews(storageKey, { limit: maxViews })
    setSavedViews(views)
  }, [maxViews, storageKey])

  useEffect(() => {
    syncSavedViews()
  }, [syncSavedViews])

  useEffect(() => {
    if (!open) return
    syncSavedViews()
  }, [open, syncSavedViews])

  useEffect(() => {
    if (!open) return
    const handleClose = () => onOpenChange(false)
    window.addEventListener('rankalpha:closeOverlays', handleClose)
    return () => window.removeEventListener('rankalpha:closeOverlays', handleClose)
  }, [open, onOpenChange])

  const currentUrl = useMemo(() => buildUrlForQuery(currentQuery), [buildUrlForQuery, currentQuery])

  const save = () => {
    if (!nameIsValid) {
      toast({ title: 'Name required', description: 'Name must be at least 2 characters.' })
      return
    }
    const created = createSavedView(storageKey, { name: trimmedName, query: currentQuery, path: savePath }, { limit: maxViews })
    if (!created) {
      toast({ title: 'Name required', description: 'Give this view a short name.' })
      return
    }
    const next = [created, ...savedViews.filter((view) => view.id !== created.id)]
    setSavedViews(writeSavedViews(storageKey, next, { limit: maxViews }))
    setViewName('')
    toast({ title: 'View saved', description: created.name })
  }

  const remove = (id: string) => {
    const next = savedViews.filter((view) => view.id !== id)
    setSavedViews(writeSavedViews(storageKey, next, { limit: maxViews }))
  }

  const copyText = async (text: string, success: { title: string; description: string }) => {
    try {
      await navigator.clipboard.writeText(text)
      toast(success)
    } catch {
      toast({ title: 'Copy failed', description: 'Clipboard access was blocked.' })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="left-auto right-0 top-0 h-[100dvh] w-[min(520px,92vw)] max-w-none translate-x-0 translate-y-0 rounded-none border-l border-outline/10 p-6 data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right sm:rounded-none sm:p-8 overflow-y-auto"
        closeClassName="right-6 top-6 h-11 w-11 rounded-full"
        overlayClassName="bg-background/70"
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-2xl border border-outline/10 bg-secondary/10 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Save current view
            </div>
            <div className="mt-2 space-y-2">
              <label className="text-xs font-semibold text-muted-foreground">
                View name
              </label>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <input
                  value={viewName}
                  onChange={(e) => setViewName(e.target.value)}
                  placeholder={namePlaceholder}
                  className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  aria-label="View name"
                  aria-invalid={showNameError}
                />
                <Button type="button" className="h-9 rounded-full" onClick={save} disabled={!nameIsValid}>
                  Save current view
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-full"
                  onClick={() => onOpenChange(false)}
                >
                  Cancel
                </Button>
              </div>
              {showNameError ? (
                <div className="text-xs text-destructive">Name must be at least 2 characters.</div>
              ) : null}
            </div>
            <div className="mt-2 text-xs text-muted-foreground">
              {helperText}
            </div>
            {!isSignedIn ? (
              <div className="mt-3 rounded-xl border border-outline/10 bg-card p-3 text-xs text-muted-foreground">
                <div className="font-semibold text-foreground">Sign in to save views across devices.</div>
                <div className="mt-1">Views are saved on this device only.</div>
              </div>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Your presets
                </div>
                {!isSignedIn ? (
                  <span className="rounded-full border border-outline/10 bg-card px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Saved on this device
                  </span>
                ) : null}
              </div>
              {showCopyCurrentLink ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-full px-3 text-xs"
                  onClick={() => void copyText(currentUrl, { title: 'Link copied', description: 'Copied the current view link.' })}
                >
                  Copy link to current view
                </Button>
              ) : null}
            </div>

            {savedViews.length ? (
              <div className="space-y-2">
                {savedViews.map((v) => {
                  const url = buildUrlForView ? buildUrlForView(v) : buildUrlForQuery(v.query || '')
                  return (
                    <div key={v.id} className="flex flex-col gap-2 rounded-2xl border border-outline/10 bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold">{v.name}</div>
                        {showQueryPreview ? (
                          <div className="mt-0.5 truncate text-xs text-muted-foreground">
                            {v.query ? `?${v.query}` : '(no filters)'}
                          </div>
                        ) : null}
                        {showSavedAt ? (
                          <div className={showQueryPreview ? 'mt-0.5' : 'mt-1'}>
                            <span className="text-xs text-muted-foreground">
                              Saved {new Date(v.created_at).toLocaleString()}
                            </span>
                          </div>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button type="button" size="sm" className="h-8 rounded-full px-3 text-xs" onClick={() => onLoad(v)}>
                          Load
                        </Button>
                        {showCopyPerView ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-8 rounded-full px-3 text-xs"
                            onClick={() => void copyText(url, { title: 'Link copied', description: v.name })}
                          >
                            Copy
                          </Button>
                        ) : null}
                        <Button type="button" variant="outline" size="sm" className="h-8 rounded-full px-3 text-xs" onClick={() => remove(v.id)}>
                          Delete
                        </Button>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-xl border border-outline/10 bg-secondary/10 p-3 text-left">
                <div className="text-sm font-semibold text-foreground">Create your first saved view</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Name the current filters, then click “Save current view”.
                </div>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
