'use client'

import * as React from 'react'

import { readLocalStorageJson, readSessionStorageItem, writeLocalStorageJson, writeSessionStorageItem } from '@/lib/storage'
import { useToast } from '@/components/ui/use-toast'

const COMPARE_STORAGE_KEY_V1 = 'rankalpha.compare.v1'
const COMPARE_STORAGE_KEY = 'rankalpha.compare.v2'
const COMPARE_TICKERS_STORAGE_KEY = 'rankalpha.compareTickers'
const COMPARE_SYMBOLS_STORAGE_KEY = 'rankalpha.compare.symbols'
const COMPARE_MAX = 3
const COMPARE_PERSIST_TOAST_KEY = 'rankalpha.compare.persistToast.v1'

type ComparePersistedV1 = {
  v: 1
  symbols: string[]
  baseline?: string | null
}

type ComparePersistedV2 = {
  v: 2
  symbols: string[]
  baseline?: string | null
  showDeltas?: boolean
  deltaMode?: 'abs' | 'pct'
}

type ComparePersisted = {
  v: 2
  symbols: string[]
  baseline: string | null
  showDeltas: boolean
  deltaMode: 'abs' | 'pct'
}

type CompareContextValue = {
  symbols: string[]
  max: number
  baseline: string | null

  addSymbol: (symbol: string) => 'added' | 'already' | 'full' | 'invalid'
  removeSymbol: (symbol: string) => void
  toggleSymbol: (symbol: string) => boolean
  moveSymbol: (symbol: string, direction: 'up' | 'down') => void
  clear: () => void

  replaceAll: (next: { symbols: string[]; baseline?: string | null; showDeltas?: boolean; deltaMode?: 'abs' | 'pct' }) => void
  setBaseline: (symbol: string | null) => void

  showDeltas: boolean
  setShowDeltas: (next: boolean) => void
  deltaMode: 'abs' | 'pct'
  setDeltaMode: (next: 'abs' | 'pct') => void
}

const CompareContext = React.createContext<CompareContextValue | null>(null)

function normalizeSymbol(raw: string): string {
  const upper = (raw || '').trim().toUpperCase()
  if (!upper) return ''
  if (!/^[A-Z0-9.]+$/.test(upper)) return ''
  if (upper.length < 1 || upper.length > 10) return ''
  return upper
}

export const normalizeCompareSymbol = normalizeSymbol

function normalizeSymbols(raw: string[]): string[] {
  const unique: string[] = []
  const seen = new Set<string>()
  for (const value of raw) {
    const sym = normalizeSymbol(value)
    if (!sym) continue
    if (seen.has(sym)) continue
    seen.add(sym)
    unique.push(sym)
    if (unique.length >= COMPARE_MAX) break
  }
  return unique
}

function readFromUrl(): ComparePersisted | null {
  if (typeof window === 'undefined') return null
  const pathname = (window.location.pathname || '').trim()
  const isComparePage = pathname === '/compare' || pathname.startsWith('/compare/')
  const sp = new URLSearchParams(window.location.search)
  const rawCompare = (sp.get('compare') || '').trim()
  const rawSymbols = (sp.get('symbols') || '').trim()
  const rawT = isComparePage ? (sp.get('t') || '').trim() : ''
  const rawList = rawSymbols || rawT || rawCompare
  if (!rawList) return null
  const symbols = normalizeSymbols(rawList.split(',').map((s) => s.trim()))
  if (!symbols.length) return null
  const baseParam = isComparePage ? sp.get('baseline') || sp.get('base') : sp.get('base')
  const base = normalizeSymbol((baseParam || '').trim())
  const baseline = base && symbols.includes(base) ? base : (symbols[0] ?? null)
  const deltasParam = isComparePage ? (sp.get('deltas') || '').trim().toLowerCase() : ''
  const showDeltas = !deltasParam ? true : deltasParam === '1' || deltasParam === 'true' || deltasParam === 'yes'
  return { v: 2, symbols, baseline, showDeltas, deltaMode: 'abs' }
}

function readPersisted(): ComparePersisted {
  const persistedV2 = readLocalStorageJson<ComparePersistedV2>(COMPARE_STORAGE_KEY)
  if (persistedV2 && persistedV2.v === 2) {
    const symbols = Array.isArray(persistedV2.symbols) ? normalizeSymbols(persistedV2.symbols) : []
    const baselineRaw = persistedV2.baseline ? normalizeSymbol(persistedV2.baseline) : null
    const baseline = baselineRaw && symbols.includes(baselineRaw) ? baselineRaw : (symbols[0] ?? null)
    return {
      v: 2,
      symbols,
      baseline,
      showDeltas: persistedV2.showDeltas ?? true,
      deltaMode: persistedV2.deltaMode === 'pct' ? 'pct' : 'abs',
    }
  }

  const tickerFallback = readLocalStorageJson<string[]>(COMPARE_SYMBOLS_STORAGE_KEY)
    ?? readLocalStorageJson<string[]>(COMPARE_TICKERS_STORAGE_KEY)
  if (Array.isArray(tickerFallback) && tickerFallback.length) {
    const symbols = normalizeSymbols(tickerFallback)
    const baseline = symbols[0] ?? null
    return { v: 2, symbols, baseline, showDeltas: true, deltaMode: 'abs' }
  }

  const persistedV1 = readLocalStorageJson<ComparePersistedV1>(COMPARE_STORAGE_KEY_V1)
  if (!persistedV1 || persistedV1.v !== 1) {
    return { v: 2, symbols: [], baseline: null, showDeltas: true, deltaMode: 'abs' }
  }

  const symbols = Array.isArray(persistedV1.symbols) ? normalizeSymbols(persistedV1.symbols) : []
  const baselineRaw = persistedV1.baseline ? normalizeSymbol(persistedV1.baseline) : null
  const baseline = baselineRaw && symbols.includes(baselineRaw) ? baselineRaw : (symbols[0] ?? null)
  return { v: 2, symbols, baseline, showDeltas: true, deltaMode: 'abs' }
}

function writePersisted(next: ComparePersisted) {
  writeLocalStorageJson(COMPARE_STORAGE_KEY, next)
  writeLocalStorageJson(COMPARE_TICKERS_STORAGE_KEY, next.symbols)
  writeLocalStorageJson(COMPARE_SYMBOLS_STORAGE_KEY, next.symbols)
}

export type ComparePageMode = 'table' | 'cards'

export function buildComparePageUrl({
  symbols,
  baseline,
  mode = 'table',
  deltas = true,
}: {
  symbols: string[]
  baseline: string | null
  mode?: ComparePageMode
  deltas?: boolean
}): string {
  const normalizedSymbols = normalizeSymbols(symbols)
  const params = new URLSearchParams()
  if (normalizedSymbols.length) params.set('symbols', normalizedSymbols.join(','))
  const base = baseline ? normalizeSymbol(baseline) : ''
  if (base && normalizedSymbols.includes(base)) params.set('baseline', base)
  params.set('mode', mode)
  params.set('deltas', deltas ? '1' : '0')
  const qs = params.toString()
  return qs ? `/compare?${qs}` : '/compare'
}

export function CompareProvider({ children }: { children: React.ReactNode }) {
  const { toast } = useToast()
  // Important: keep the initial render deterministic across SSR + client hydration.
  // We hydrate from localStorage after mount.
  const [hydrated, setHydrated] = React.useState(false)
  const [state, setState] = React.useState<ComparePersisted>({
    v: 2,
    symbols: [],
    baseline: null,
    showDeltas: true,
    deltaMode: 'abs',
  })
  const stateRef = React.useRef<ComparePersisted>(state)

  const applyState = React.useCallback((next: ComparePersisted) => {
    stateRef.current = next
    setState(next)
  }, [])

  React.useEffect(() => {
    applyState(readFromUrl() ?? readPersisted())
    setHydrated(true)
  }, [applyState])

  React.useEffect(() => {
    if (!hydrated) return
    writePersisted(state)
  }, [state, hydrated])

  React.useEffect(() => {
    if (!hydrated) return
    if (state.symbols.length < 1) return
    if (readSessionStorageItem(COMPARE_PERSIST_TOAST_KEY)) return
    writeSessionStorageItem(COMPARE_PERSIST_TOAST_KEY, '1')
    toast({ title: 'Compare selection saved on this device.', duration: 2500 })
  }, [hydrated, state.symbols.length, toast])

  React.useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== COMPARE_STORAGE_KEY && event.key !== COMPARE_STORAGE_KEY_V1) return
      applyState(readPersisted())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [applyState])

  const addSymbol = (symbol: string): 'added' | 'already' | 'full' | 'invalid' => {
    const normalized = normalizeSymbol(symbol)
    if (!normalized) return 'invalid'
    const prev = stateRef.current
    if (prev.symbols.includes(normalized)) {
      return 'already'
    }

    if (prev.symbols.length >= COMPARE_MAX) return 'full'

    const nextSymbols = [...prev.symbols, normalized]
    const nextBaseline = prev.baseline && nextSymbols.includes(prev.baseline) ? prev.baseline : (nextSymbols[0] ?? null)
    applyState({ ...prev, symbols: nextSymbols, baseline: nextBaseline })
    return 'added'
  }

  const removeSymbol = (symbol: string) => {
    const normalized = normalizeSymbol(symbol)
    if (!normalized) return
    const prev = stateRef.current
    if (!prev.symbols.includes(normalized)) return
    const nextSymbols = prev.symbols.filter((s) => s !== normalized)
    const nextBaseline = prev.baseline === normalized ? (nextSymbols[0] ?? null) : (prev.baseline ?? (nextSymbols[0] ?? null))
    applyState({ ...prev, symbols: nextSymbols, baseline: nextBaseline })
  }

  const toggleSymbol = (symbol: string): boolean => {
    const normalized = normalizeSymbol(symbol)
    if (!normalized) return false
    const prev = stateRef.current
    if (prev.symbols.includes(normalized)) {
      const nextSymbols = prev.symbols.filter((s) => s !== normalized)
      const nextBaseline = prev.baseline === normalized ? (nextSymbols[0] ?? null) : (prev.baseline ?? (nextSymbols[0] ?? null))
      applyState({ ...prev, symbols: nextSymbols, baseline: nextBaseline })
      return false
    }
    if (prev.symbols.length >= COMPARE_MAX) return false
    const nextSymbols = [...prev.symbols, normalized]
    const nextBaseline = prev.baseline && nextSymbols.includes(prev.baseline) ? prev.baseline : (nextSymbols[0] ?? null)
    applyState({ ...prev, symbols: nextSymbols, baseline: nextBaseline })
    return true
  }

  const moveSymbol = (symbol: string, direction: 'up' | 'down') => {
    const normalized = normalizeSymbol(symbol)
    if (!normalized) return
    const prev = stateRef.current
    const idx = prev.symbols.indexOf(normalized)
    if (idx < 0) return

    const nextIdx = direction === 'up' ? idx - 1 : idx + 1
    if (nextIdx < 0 || nextIdx >= prev.symbols.length) return

    const nextSymbols = [...prev.symbols]
    const tmp = nextSymbols[idx]
    nextSymbols[idx] = nextSymbols[nextIdx]
    nextSymbols[nextIdx] = tmp

    const nextBaseline = prev.baseline && nextSymbols.includes(prev.baseline) ? prev.baseline : (nextSymbols[0] ?? null)
    applyState({ ...prev, symbols: nextSymbols, baseline: nextBaseline })
  }

  const clear = () => {
    const prev = stateRef.current
    applyState({ ...prev, v: 2, symbols: [], baseline: null })
  }

  const replaceAll = (next: { symbols: string[]; baseline?: string | null; showDeltas?: boolean; deltaMode?: 'abs' | 'pct' }) => {
    const symbols = normalizeSymbols(next.symbols)
    const baselineRaw = next.baseline ? normalizeSymbol(next.baseline) : null
    const baseline = baselineRaw && symbols.includes(baselineRaw) ? baselineRaw : (symbols[0] ?? null)
    applyState({
      ...stateRef.current,
      v: 2,
      symbols,
      baseline,
      showDeltas: next.showDeltas ?? stateRef.current.showDeltas,
      deltaMode: next.deltaMode === 'pct' ? 'pct' : next.deltaMode === 'abs' ? 'abs' : stateRef.current.deltaMode,
    })
  }

  const setBaseline = (symbol: string | null) => {
    if (!symbol) {
      const prev = stateRef.current
      const fallback = prev.symbols[0] ?? null
      if ((prev.baseline ?? null) === fallback) return
      applyState({ ...prev, baseline: fallback })
      return
    }
    const normalized = normalizeSymbol(symbol)
    if (!normalized) return
    const prev = stateRef.current
    if (!prev.symbols.includes(normalized)) return
    if (prev.baseline === normalized) return
    applyState({ ...prev, baseline: normalized })
  }

  const value: CompareContextValue = {
    symbols: state.symbols,
    max: COMPARE_MAX,
    baseline: state.baseline ?? null,

    addSymbol,
    removeSymbol,
    toggleSymbol,
    moveSymbol,
    clear,

    replaceAll,
    setBaseline,

    showDeltas: state.showDeltas,
    setShowDeltas: (next) => applyState({ ...stateRef.current, showDeltas: next }),
    deltaMode: state.deltaMode,
    setDeltaMode: (next) => applyState({ ...stateRef.current, deltaMode: next }),
  }

  return <CompareContext.Provider value={value}>{children}</CompareContext.Provider>
}

export function useCompare() {
  const ctx = React.useContext(CompareContext)
  if (!ctx) throw new Error('useCompare must be used within CompareProvider')
  return ctx
}
