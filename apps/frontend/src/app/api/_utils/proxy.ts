import { createHash } from 'crypto'
import { NextRequest, NextResponse } from 'next/server'
import { buildAuthHeaders } from '@/app/api/_utils/auth'
import { buildUpstreamUrl, cacheControlForPayload } from '@/app/api/_utils/upstream'

type ProxyGetJsonOptions = {
  upstreamPath: string
  searchParams?: URLSearchParams | string
  revalidate?: number
  tags?: string[]
  cacheControl?: string
  auth?: 'passthrough' | 'none'
  cache?: 'auto' | 'no-store'
  transform?: (data: any) => any
}

function truncateError(text: string, max = 1200) {
  const trimmed = (text || '').trim()
  if (trimmed.length <= max) return trimmed
  return `${trimmed.slice(0, max)}…`
}

function getAuthServiceToken(): string | null {
  return (process.env.AUTH_SERVICE_TOKEN || '').trim() || null
}

export async function proxyGetJson(request: NextRequest, opts: ProxyGetJsonOptions) {
  const target = buildUpstreamUrl(opts.upstreamPath, opts.searchParams)
  const tags = opts.tags ?? []
  const revalidate = opts.revalidate ?? 300
  const cacheControl = opts.cacheControl ?? `s-maxage=${revalidate}, stale-while-revalidate=${revalidate * 2}`

  const useAuth = (opts.auth ?? 'passthrough') === 'passthrough'
  const headers = useAuth ? await buildAuthHeaders(request) : undefined
  const isAuthed = Boolean(headers?.has('Authorization'))
  const forceNoStore = (opts.cache ?? 'auto') === 'no-store'
  const authedCacheControl = `private, max-age=${revalidate}, stale-while-revalidate=${revalidate * 2}`
  const cacheKeySuffix = (() => {
    if (!isAuthed || !headers) return null
    const auth = headers.get('Authorization') || ''
    if (!auth) return null
    try {
      return createHash('sha1').update(auth).digest('hex')
    } catch {
      return null
    }
  })()

  try {
    const res = await fetch(
      target,
      forceNoStore
        ? { cache: 'no-store', headers }
        : {
            next: { revalidate, tags },
            headers: cacheKeySuffix
              ? new Headers({ ...Object.fromEntries(headers ?? []), 'X-RA-Cache-Key': cacheKeySuffix })
              : headers,
          }
    )

    if (!res.ok) {
      const text = await res.text()
      return NextResponse.json(
        { error: 'Upstream error', details: truncateError(text) },
        { status: res.status }
      )
    }

    const data = await res.json()
    const payload = opts.transform ? opts.transform(data) : data
    return NextResponse.json(payload, {
      headers: {
        'Cache-Control': forceNoStore
          ? 'no-store, max-age=0'
          : cacheControlForPayload(payload, isAuthed ? authedCacheControl : cacheControl),
      },
    })
  } catch (err: any) {
    return NextResponse.json(
      { error: 'Failed to reach API', details: truncateError(String(err)) },
      { status: 502 }
    )
  }
}

type ProxyServiceJsonOptions = {
  upstreamPath: string
  searchParams?: URLSearchParams | string
  method?: 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: BodyInit | null
  headers?: HeadersInit
}

export async function proxyServiceJson(opts: ProxyServiceJsonOptions) {
  const target = buildUpstreamUrl(opts.upstreamPath, opts.searchParams)
  const token = getAuthServiceToken()
  if (!token) {
    return NextResponse.json({ error: 'AUTH_SERVICE_TOKEN not configured' }, { status: 500 })
  }

  const headers = new Headers(opts.headers)
  headers.set('Accept', 'application/json')
  headers.set('X-RA-Service-Token', token)
  if (opts.body !== undefined && opts.body !== null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  try {
    const res = await fetch(target, {
      method: opts.method ?? 'POST',
      headers,
      body: opts.body,
      cache: 'no-store',
    })

    const text = await res.text().catch(() => '')
    let data: any = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = text ? { raw: truncateError(text) } : null
    }

    if (!res.ok) {
      return NextResponse.json({ error: 'Upstream error', details: data }, { status: res.status })
    }

    return NextResponse.json(data ?? { ok: true }, { status: res.status })
  } catch (err: any) {
    return NextResponse.json({ error: 'Failed to reach API', details: truncateError(String(err)) }, { status: 502 })
  }
}
