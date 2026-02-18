'use client'

import { useCallback } from 'react'

import { useToast } from '@/components/ui/use-toast'
import type { SavedView } from '@/lib/saved_views'

type ReplaceRouter = {
  replace: (url: string, options?: { scroll?: boolean }) => void
}

export function useLoadSavedView({
  basePath,
  router,
  removeParams = ['views'],
  title = 'View loaded',
}: {
  basePath: string
  router: ReplaceRouter
  removeParams?: string[]
  title?: string
}) {
  const { toast } = useToast()

  return useCallback((view: SavedView) => {
    const params = new URLSearchParams(view.query || '')
    removeParams.forEach((key) => params.delete(key))
    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl, { scroll: false })
    toast({ title, description: view.name })
  }, [basePath, removeParams, router, title, toast])
}
