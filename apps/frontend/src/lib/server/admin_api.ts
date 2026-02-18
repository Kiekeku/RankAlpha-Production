import 'server-only'

import { buildUpstreamUrl } from '@/app/api/_utils/upstream'

export type AdminApiTokenMode = 'service' | 'service-or-admin'

export type AdminApiResult<T> = {
  ok: boolean
  message: string
  payload: T | null
}

function getAuthServiceToken(): string | null {
  return (process.env.AUTH_SERVICE_TOKEN || '').trim() || null
}

function getAdminBearerToken(): string | null {
  return (process.env.BACKEND_ADMIN_BEARER_TOKEN || process.env.ADMIN_BEARER_TOKEN || '').trim() || null
}

function resolveTokens(mode: AdminApiTokenMode): { serviceToken: string | null; adminToken: string | null } {
  const serviceToken = getAuthServiceToken()
  if (mode === 'service') return { serviceToken, adminToken: null }
  return { serviceToken, adminToken: getAdminBearerToken() }
}

function applyDefaultHeaders(headers: Headers, init: RequestInit) {
  headers.set('Accept', 'application/json')
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
}

async function readResponsePayload(response: Response): Promise<{ payload: any; message: string }> {
  let payload: any = null
  let message = ''
  try {
    payload = await response.json()
    if (payload && typeof payload.detail === 'string') {
      message = payload.detail
    }
  } catch {
    try {
      message = await response.text()
    } catch {
      message = ''
    }
  }

  if (!message) {
    message = response.ok ? 'Request completed.' : response.statusText || 'Request failed.'
  }

  return { payload, message }
}

export async function adminApiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
  opts: {
    tokenMode?: AdminApiTokenMode
    missingTokenMessage?: string
  } = {},
): Promise<AdminApiResult<T>> {
  const tokenMode = opts.tokenMode ?? 'service'
  const { serviceToken, adminToken } = resolveTokens(tokenMode)

  const headers = new Headers(init.headers)
  applyDefaultHeaders(headers, init)

  const missingTokenMessage =
    opts.missingTokenMessage ??
    (tokenMode === 'service' ? 'AUTH_SERVICE_TOKEN not configured' : 'AUTH_SERVICE_TOKEN or BACKEND_ADMIN_BEARER_TOKEN not configured')

  if (!serviceToken && !adminToken) {
    return { ok: false, message: missingTokenMessage, payload: null }
  }

  if (serviceToken) {
    headers.set('X-RA-Service-Token', serviceToken)
  } else if (adminToken) {
    headers.set('X-RA-Service-Token', adminToken)
    headers.set('Authorization', `Bearer ${adminToken}`)
  }

  const response = await fetch(buildUpstreamUrl(path), {
    ...init,
    headers,
    cache: 'no-store',
  })

  const { payload, message } = await readResponsePayload(response)
  return { ok: response.ok, message, payload: payload as T }
}

export function hasAuthServiceToken(): boolean {
  return Boolean(getAuthServiceToken())
}

