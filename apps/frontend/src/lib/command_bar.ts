import { readLocalStorageJson, writeLocalStorageJson } from '@/lib/storage'

export type RecentTicker = {
  symbol: string
  company_name?: string
  last_seen_at: string
}

export type SavedView = {
  id: string
  name: string
  url: string
  saved_at: string
}

const RECENTS_KEY = 'rankalpha.command_bar.recents.v1'
const SAVED_VIEWS_KEY = 'rankalpha.command_bar.saved_views.v1'

const MAX_RECENTS = 16
const MAX_SAVED_VIEWS = 16

function safeUpperSymbol(raw: string): string {
  const sym = (raw || '').trim().toUpperCase()
  if (!sym) return ''
  if (!/^[A-Z0-9.]+$/.test(sym)) return ''
  if (sym.length < 1 || sym.length > 10) return ''
  return sym
}

export function listRecentTickers(): RecentTicker[] {
  const stored = readLocalStorageJson<RecentTicker[]>(RECENTS_KEY)
  if (!Array.isArray(stored)) return []
  return stored
    .filter((x) => x && typeof x.symbol === 'string' && typeof x.last_seen_at === 'string')
    .map((x) => ({ symbol: x.symbol, company_name: x.company_name, last_seen_at: x.last_seen_at }))
    .slice(0, MAX_RECENTS)
}

export function addRecentTicker(input: { symbol: string; company_name?: string }): void {
  const symbol = safeUpperSymbol(input.symbol)
  if (!symbol) return

  const now = new Date().toISOString()
  const prev = listRecentTickers()
  const next: RecentTicker[] = [
    { symbol, company_name: input.company_name?.trim() || undefined, last_seen_at: now },
    ...prev.filter((x) => x.symbol !== symbol),
  ].slice(0, MAX_RECENTS)

  writeLocalStorageJson(RECENTS_KEY, next)
}

export function listSavedViews(): SavedView[] {
  const stored = readLocalStorageJson<SavedView[]>(SAVED_VIEWS_KEY)
  if (!Array.isArray(stored)) return []
  return stored
    .filter((x) => x && typeof x.id === 'string' && typeof x.name === 'string' && typeof x.url === 'string')
    .slice(0, MAX_SAVED_VIEWS)
}

export function addSavedView(input: { url: string; name: string }): SavedView | null {
  const url = (input.url || '').trim()
  const name = (input.name || '').trim()
  if (!url || !name) return null

  const now = new Date().toISOString()
  const id = `${now}:${Math.random().toString(16).slice(2)}`

  const prev = listSavedViews()
  const next: SavedView[] = [{ id, url, name, saved_at: now }, ...prev].slice(0, MAX_SAVED_VIEWS)
  writeLocalStorageJson(SAVED_VIEWS_KEY, next)
  return next[0]
}

export function removeSavedView(id: string): void {
  const prev = listSavedViews()
  const next = prev.filter((x) => x.id !== id)
  writeLocalStorageJson(SAVED_VIEWS_KEY, next)
}

