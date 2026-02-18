import { readLocalStorageJson, writeLocalStorageJson } from '@/lib/storage'

export type SavedView = {
  id: string
  name: string
  query: string
  created_at: string
  path?: string
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

export function readSavedViews(storageKey: string, { limit = 25 }: { limit?: number } = {}): SavedView[] {
  const stored = readLocalStorageJson<unknown>(storageKey)
  if (!Array.isArray(stored)) return []
  const out: SavedView[] = []
  for (const item of stored) {
    if (!isObject(item)) continue
    if (typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.query !== 'string') continue
    const created_at = typeof item.created_at === 'string' ? item.created_at : ''
    if (!created_at) continue
    const path = typeof item.path === 'string' ? item.path : undefined
    out.push({ id: item.id, name: item.name, query: item.query, created_at, path })
  }
  return out.slice(0, Math.max(1, limit))
}

export function writeSavedViews(storageKey: string, views: SavedView[], { limit = 25 }: { limit?: number } = {}): SavedView[] {
  const trimmed = (views || []).slice(0, Math.max(1, limit))
  writeLocalStorageJson(storageKey, trimmed)
  return trimmed
}

export function createSavedView(storageKey: string, input: { name: string; query: string; path?: string }, { limit = 25 }: { limit?: number } = {}): SavedView | null {
  const name = (input.name || '').trim()
  if (!name) return null
  const query = (input.query || '').trim()
  const path = (input.path || '').trim() || undefined
  const next: SavedView = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name,
    query,
    path,
    created_at: new Date().toISOString(),
  }
  const prev = readSavedViews(storageKey, { limit })
  writeSavedViews(storageKey, [next, ...prev.filter((v) => v.id !== next.id)], { limit })
  return next
}

export function removeSavedView(storageKey: string, id: string, { limit = 25 }: { limit?: number } = {}): SavedView[] {
  const prev = readSavedViews(storageKey, { limit })
  const next = prev.filter((v) => v.id !== id)
  return writeSavedViews(storageKey, next, { limit })
}

