import { existsSync, readFileSync } from 'fs'

const DEFAULT_INTERNAL_API_URL = 'http://localhost:6080'
const NO_STORE_CACHE_CONTROL = 'no-store, max-age=0'

function safeHostname(baseUrl: string | undefined): string | null {
  if (!baseUrl) return null
  try {
    return new URL(baseUrl).hostname
  } catch {
    return null
  }
}

function isRunningInDocker(): boolean {
  try {
    if (existsSync('/.dockerenv')) return true
  } catch {
    // ignore
  }
  try {
    const cgroup = readFileSync('/proc/1/cgroup', 'utf8')
    return cgroup.includes('docker') || cgroup.includes('containerd') || cgroup.includes('kubepods')
  } catch {
    return false
  }
}

function coerceLocalhostWhenNotInDocker(baseUrl: string): string {
  try {
    const url = new URL(baseUrl)
    if (url.hostname === 'api' && !isRunningInDocker()) {
      url.hostname = 'localhost'
      return url.toString().replace(/\/$/, '')
    }
  } catch {
    // ignore
  }
  return baseUrl
}

function normalizeBase(url: string): string {
  const trimmed = (url || '').trim()
  if (!trimmed) {
    return DEFAULT_INTERNAL_API_URL
  }
  try {
    // Validate the base; fall back if malformed (prevents build-time crashes).
    new URL(trimmed)
  } catch {
    return DEFAULT_INTERNAL_API_URL
  }

  return trimmed.endsWith('/') ? trimmed.slice(0, -1) : trimmed
}

export function getInternalApiBase(): string {
  const internalRaw = process.env.INTERNAL_API_URL
  const publicRaw = process.env.NEXT_PUBLIC_API_URL
  const raw = internalRaw || publicRaw || DEFAULT_INTERNAL_API_URL
  const normalized = normalizeBase(raw)

  const internalHost = safeHostname(internalRaw)
  const publicHost = safeHostname(publicRaw)
  if (
    internalHost === 'api' &&
    publicHost &&
    (publicHost === 'localhost' || publicHost === '127.0.0.1')
  ) {
    return normalizeBase(publicRaw as string)
  }

  if (!isRunningInDocker()) {
    return coerceLocalhostWhenNotInDocker(normalized)
  }

  return normalized
}

export function buildUpstreamUrl(path: string, searchParams?: URLSearchParams | string): string {
  const base = getInternalApiBase()
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const url = new URL(normalizedPath, `${base}/`)

  if (searchParams instanceof URLSearchParams) {
    searchParams.forEach((value, key) => {
      url.searchParams.append(key, value)
    })
  } else if (typeof searchParams === 'string' && searchParams.length > 0) {
    const params = new URLSearchParams(searchParams)
    params.forEach((value, key) => {
      url.searchParams.append(key, value)
    })
  }

  return url.toString()
}

function isEmptyPayload(payload: unknown): boolean {
  if (Array.isArray(payload)) {
    return payload.length === 0
  }
  if (!payload || typeof payload !== 'object') return false
  if (Object.keys(payload).length === 0) return true
  if (!('status' in payload)) return false
  const status = (payload as { status?: unknown }).status
  return typeof status === 'string' && status.trim().toLowerCase() === 'empty'
}

export function cacheControlForPayload(payload: unknown, cacheControl: string): string {
  return isEmptyPayload(payload) ? NO_STORE_CACHE_CONTROL : cacheControl
}
