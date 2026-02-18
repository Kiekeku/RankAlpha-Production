import { NextResponse } from 'next/server'
import { buildUpstreamUrl, cacheControlForPayload } from '@/app/api/_utils/upstream'

export type QueryParams = Record<string, string | number | boolean | null | undefined> | undefined

export type OkPart<T> = { ok: true; data: T }
export type ErrPart = { ok: false; status: number; error: string }
export type Part<T> = OkPart<T> | ErrPart

export function buildSearchParams(params: QueryParams): URLSearchParams {
  const qs = new URLSearchParams()
  if (!params) return qs
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue
    qs.set(key, String(value))
  }
  return qs
}

export function truncateError(text: string, max = 1200): string {
  const trimmed = (text || '').trim()
  if (trimmed.length <= max) return trimmed
  return `${trimmed.slice(0, max)}…`
}

export function createOverviewPartFetcher({
  authHeaders,
  isAuthed,
  scopeTag,
}: {
  authHeaders: Headers
  isAuthed: boolean
  scopeTag: string
}) {
  return async function fetchPart<T>(
    path: string,
    params: QueryParams,
    opts: { revalidate: number; tags: string[]; headers?: HeadersInit } = { revalidate: 300, tags: [] },
  ): Promise<Part<T>> {
    const target = buildUpstreamUrl(path, buildSearchParams(params))
    try {
      const headers = opts.headers ?? authHeaders
      const res = await fetch(
        target,
        isAuthed
          ? { headers, cache: 'no-store' }
          : { headers, next: { revalidate: opts.revalidate, tags: ['overview', scopeTag, ...opts.tags] } },
      )
      if (!res.ok) {
        const text = await res.text()
        return { ok: false, status: res.status, error: truncateError(text) }
      }
      const data = (await res.json()) as T
      return { ok: true, data }
    } catch (err: any) {
      return { ok: false, status: 502, error: truncateError(String(err)) }
    }
  }
}

export function buildOverviewResponse(payload: unknown, isAuthed: boolean) {
  return NextResponse.json(payload, {
    headers: {
      'Cache-Control': isAuthed
        ? 'private, no-store, max-age=0'
        : cacheControlForPayload(payload, 'public, max-age=60, s-maxage=180, stale-while-revalidate=600'),
      Vary: 'Authorization',
    },
  })
}
