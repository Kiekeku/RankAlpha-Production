'use client'

import { useCallback, useMemo } from 'react'
import type { ReadonlyURLSearchParams } from 'next/navigation'

type ReplaceRouter = {
  replace: (url: string, options?: { scroll?: boolean }) => void
}

export function useSavedViewsDrawer({
  pathname,
  fallbackPath,
  searchParams,
  router,
  paramKey = 'views',
}: {
  pathname?: string | null
  fallbackPath: string
  searchParams: ReadonlyURLSearchParams
  router: ReplaceRouter
  paramKey?: string
}) {
  const viewsOpen = useMemo(() => {
    const raw = (searchParams.get(paramKey) || '').trim().toLowerCase()
    return raw === '1' || raw === 'true' || raw === 'yes'
  }, [paramKey, searchParams])

  const basePath = pathname || fallbackPath

  const openViews = useCallback(() => {
    if (viewsOpen) return
    const params = new URLSearchParams(searchParams.toString())
    params.set(paramKey, '1')
    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl, { scroll: false })
  }, [basePath, paramKey, router, searchParams, viewsOpen])

  const closeViews = useCallback(() => {
    if (!viewsOpen) return
    const params = new URLSearchParams(searchParams.toString())
    params.delete(paramKey)
    const qs = params.toString()
    const nextUrl = qs ? `${basePath}?${qs}` : basePath
    router.replace(nextUrl, { scroll: false })
  }, [basePath, paramKey, router, searchParams, viewsOpen])

  const onOpenChange = useCallback(
    (next: boolean) => {
      if (next) {
        openViews()
      } else {
        closeViews()
      }
    },
    [closeViews, openViews],
  )

  return { viewsOpen, openViews, closeViews, onOpenChange }
}

export function useSavedViewsLinks({
  pathname,
  fallbackPath,
  searchParams,
  excludeParams = ['views', 'page'],
}: {
  pathname?: string | null
  fallbackPath: string
  searchParams: ReadonlyURLSearchParams
  excludeParams?: string[]
}) {
  const savedViewsBasePath = useMemo(() => pathname || fallbackPath, [fallbackPath, pathname])

  const currentSavedViewQuery = useMemo(() => {
    const params = new URLSearchParams(searchParams.toString())
    excludeParams.forEach((key) => params.delete(key))
    return params.toString()
  }, [excludeParams, searchParams])

  const buildSavedViewUrlForQuery = useCallback((query: string) => {
    const rel = query ? `${savedViewsBasePath}?${query}` : savedViewsBasePath
    if (typeof window === 'undefined') return rel
    return `${window.location.origin}${rel}`
  }, [savedViewsBasePath])

  return { currentSavedViewQuery, savedViewsBasePath, buildSavedViewUrlForQuery }
}
