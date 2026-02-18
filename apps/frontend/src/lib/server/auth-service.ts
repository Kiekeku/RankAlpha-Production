import { getInternalApiBase } from '@/app/api/_utils/upstream'

const BACKEND_PREFIX = '/api/v1'

function stripBackendPrefix(baseUrl: string): string {
  const normalized = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl
  if (normalized.toLowerCase().endsWith(BACKEND_PREFIX)) {
    return normalized.slice(0, -BACKEND_PREFIX.length) || '/'
  }
  return normalized
}

function resolveBaseUrl(): string {
  return stripBackendPrefix(getInternalApiBase())
}

function getServiceToken(): string | null {
  return (process.env.AUTH_SERVICE_TOKEN || '').trim() || null
}

export interface AuthUser {
  user_id: number
  email: string
  full_name?: string | null
  avatar_url?: string | null
  provider?: string | null
  provider_account_id?: string | null
  roles: string[]
  is_active: boolean
  last_login_at?: string | null
  created_at: string
  updated_at: string
}

interface SyncPayload {
  email: string
  full_name?: string | null
  avatar_url?: string | null
  provider?: string | null
  providerAccountId?: string | null
  metadata?: Record<string, unknown>
}

async function callAuthApi<T>(path: string, init?: RequestInit, requireServiceToken = true): Promise<T> {
  const base = resolveBaseUrl()
  const url = `${base}${path}`
  const headers = new Headers(init?.headers)
  headers.set('Accept', 'application/json')
  if (!(init?.method && init.method.toUpperCase() === 'GET')) {
    headers.set('Content-Type', 'application/json')
  }

  const serviceToken = getServiceToken()
  if (requireServiceToken && !serviceToken) {
    throw new Error('AUTH_SERVICE_TOKEN not configured')
  }
  if (requireServiceToken && serviceToken) {
    headers.set('X-RA-Service-Token', serviceToken)
  }

  const response = await fetch(url, {
    ...init,
    headers,
    cache: 'no-store',
  })

  if (!response.ok) {
    let detail: unknown
    try {
      detail = await response.json()
    } catch {
      detail = await response.text()
    }
    throw new Error(`Auth service request failed (${response.status}): ${JSON.stringify(detail)}`)
  }

  return response.json() as Promise<T>
}

export async function syncUserProfile(payload: SyncPayload): Promise<AuthUser> {
  return callAuthApi<AuthUser>('/api/v1/auth/sync', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, true)
}

export async function fetchUserById(userId: number): Promise<AuthUser> {
  return callAuthApi<AuthUser>(`/api/v1/auth/users/${userId}`, { method: 'GET' }, true)
}
