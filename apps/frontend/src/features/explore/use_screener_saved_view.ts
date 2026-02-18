'use client'

import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'

import type { SavedView } from '@/lib/saved_views'
import { writeLocalStorageJson } from '@/lib/storage'

type ReplaceRouter = {
  replace: (url: string, options?: { scroll?: boolean }) => void
}

type ToastFn = (opts: { title: string; description?: string }) => void

function normalizeScreenerBase(raw?: string | null) {
  const base = (raw || '').trim() || '/screener'
  return base.startsWith('/screener') ? base : '/screener'
}

export function useScreenerSavedView<SortKey extends string>({
  savedViewsBasePath,
  normalizedInitialStyles,
  defaultMovementWindowDays,
  router,
  toast,
  suspendUrlSyncRef,
  tabStorageKey,
  setSearchQuery,
  setStyles,
  setSources,
  setStyleMatchAll,
  setSourceMatchAll,
  setAppearancesMin,
  setStylesMin,
  setSortBy,
  setSortOrder,
  setBias,
  setMovementFilter,
  setMovementStyle,
  setMovementWindowDays,
  setBreadthMode,
  setBreadthDrilldown,
  setPage,
}: {
  savedViewsBasePath: string
  normalizedInitialStyles: string[]
  defaultMovementWindowDays: number
  router: ReplaceRouter
  toast: ToastFn
  suspendUrlSyncRef: MutableRefObject<boolean>
  tabStorageKey: string
  setSearchQuery: (value: string) => void
  setStyles: (value: string[]) => void
  setSources: (value: string[]) => void
  setStyleMatchAll: (value: boolean) => void
  setSourceMatchAll: (value: boolean) => void
  setAppearancesMin: (value: number) => void
  setStylesMin: (value: number) => void
  setSortBy: Dispatch<SetStateAction<SortKey>>
  setSortOrder: (value: 'asc' | 'desc') => void
  setBias: (value: 'all' | 'bullish' | 'bearish') => void
  setMovementFilter: (value: 'entered' | 'reentered' | 'dropped' | 'entrants' | null) => void
  setMovementStyle: (value: string | null) => void
  setMovementWindowDays: (value: number) => void
  setBreadthMode: (value: 'flow' | 'legacy') => void
  setBreadthDrilldown: (value: any) => void
  setPage: (value: number) => void
}) {
  const buildSavedViewUrlForView = useCallback((view: SavedView) => {
    const base = normalizeScreenerBase(view.path || savedViewsBasePath)
    const rel = view.query ? `${base}?${view.query}` : base
    if (typeof window === 'undefined') return rel
    return `${window.location.origin}${rel}`
  }, [savedViewsBasePath])

  const applySavedView = useCallback((view: SavedView) => {
    const basePath = normalizeScreenerBase(view.path || savedViewsBasePath)

    suspendUrlSyncRef.current = true
    try {
      const params = new URLSearchParams(view.query || '')
      params.delete('views')

      const tabRaw = (params.get('tab') || '').trim().toLowerCase()
      const tab = tabRaw === 'changes' || tabRaw === 'breadth' || tabRaw === 'results' ? tabRaw : 'results'
      params.set('tab', tab)
      writeLocalStorageJson(tabStorageKey, { v: 1, tab })

      const getAll = (key: string) => params.getAll(key).map((s) => (s || '').trim()).filter(Boolean)

      const q = (params.get('q') || params.get('symbol_filter') || '').trim()
      const st = getAll('styles')
      const so = getAll('sources')
      const sl = (params.get('style_logic') || '').trim().toLowerCase()
      const sol = (params.get('source_logic') || '').trim().toLowerCase()
      const am = Number(params.get('appearances_min') || 0) || 0
      const sm = Number(params.get('styles_min') || 0) || 0
      const sb = (params.get('sort_by') || '').trim()
      const sox = (params.get('sort_order') || '').trim().toLowerCase() as 'asc' | 'desc' | ''
      const biasParam = (params.get('bias') || '').trim().toLowerCase() as 'all' | 'bullish' | 'bearish' | ''
      const mv = (params.get('movement') || '').trim().toLowerCase() as 'entered' | 'reentered' | 'dropped' | 'entrants' | ''
      const mvStyle = (params.get('movement_style') || '').trim()
      const mvWindowRaw = (params.get('movement_window') || '').trim()
      const mvWindow = Number(mvWindowRaw)
      const breadthParam = (params.get('breadth') || '').trim().toLowerCase() as 'flow' | 'legacy' | ''

      setSearchQuery(q)
      setStyles(st.length ? st : normalizedInitialStyles.length ? normalizedInitialStyles : [])
      setSources(so)
      setStyleMatchAll(sl !== 'any')
      setSourceMatchAll(sol !== 'any')
      setAppearancesMin(Math.max(0, am))
      setStylesMin(Math.max(0, sm))
      const allowedSort = new Set([
        'consensus_score',
        'appearances',
        'styles_distinct',
        'sources_distinct',
        'rank_best',
        'min_style_rank_pct',
        'symbol',
      ])
      const nextSort = sb && allowedSort.has(sb) ? sb : 'consensus_score'
      setSortBy(nextSort as SortKey)
      setSortOrder(sox === 'asc' || sox === 'desc' ? sox : 'desc')
      setBias(biasParam === 'bullish' || biasParam === 'bearish' || biasParam === 'all' ? biasParam : 'all')
      setMovementFilter(mv === 'entered' || mv === 'reentered' || mv === 'dropped' || mv === 'entrants' ? mv : null)
      setMovementStyle(mvStyle || null)
      setMovementWindowDays(
        Number.isFinite(mvWindow) && mvWindow > 0 ? Math.max(1, Math.min(30, Math.round(mvWindow))) : defaultMovementWindowDays
      )
      setBreadthMode(breadthParam === 'legacy' ? 'legacy' : 'flow')
      setBreadthDrilldown(null)
      setPage(1)

      const qs = params.toString()
      const nextUrl = qs ? `${basePath}?${qs}` : basePath
      router.replace(nextUrl, { scroll: false })
      toast({ title: 'View loaded', description: view.name })
    } finally {
      setTimeout(() => {
        suspendUrlSyncRef.current = false
      }, 0)
    }
  }, [
    defaultMovementWindowDays,
    normalizedInitialStyles,
    router,
    savedViewsBasePath,
    setAppearancesMin,
    setBias,
    setBreadthDrilldown,
    setBreadthMode,
    setMovementFilter,
    setMovementStyle,
    setMovementWindowDays,
    setPage,
    setSearchQuery,
    setSortBy,
    setSortOrder,
    setSources,
    setStyleMatchAll,
    setSourceMatchAll,
    setStyles,
    setStylesMin,
    suspendUrlSyncRef,
    tabStorageKey,
    toast,
  ])

  return { applySavedView, buildSavedViewUrlForView }
}
