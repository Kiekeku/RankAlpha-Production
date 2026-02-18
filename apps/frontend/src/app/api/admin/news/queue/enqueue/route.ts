import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth'

import { proxyServiceJson } from '@/app/api/_utils/proxy'
import { authOptions } from '@/lib/auth'
import { hasRole } from '@/lib/roles'
import {
  getFrontendAdminRequestContext,
  logFrontendAdminAccessEvent,
} from '@/lib/server/admin_security_log'

export const runtime = 'nodejs'
const ADMIN_ROUTE_PATH = '/api/admin/news/queue/enqueue'

export async function GET(request: NextRequest) {
  const requestContext = getFrontendAdminRequestContext(request.headers)
  logFrontendAdminAccessEvent({
    surface: 'admin_api',
    path: ADMIN_ROUTE_PATH,
    method: 'GET',
    outcome: 'forbidden',
    statusCode: 405,
    context: requestContext,
    note: 'method_not_allowed',
  })
  return NextResponse.json({ error: 'Method not allowed' }, { status: 405 })
}

interface EnqueuePayload {
  symbol?: string
  eventId?: string | null
  title?: string | null
  url?: string | null
  rawId?: string | null
  priority?: number
  force?: boolean
}

function normalizeSymbol(input: unknown): string {
  if (typeof input !== 'string') return ''
  return input.trim().toUpperCase()
}

function normalizeOptionalString(input: unknown): string | undefined {
  if (typeof input !== 'string') return undefined
  const trimmed = input.trim()
  return trimmed ? trimmed : undefined
}

function clampPriority(value: unknown, fallback = 90): number {
  const num = Number(value)
  if (!Number.isFinite(num)) return fallback
  return Math.max(-20, Math.min(100, Math.round(num)))
}

export async function POST(request: NextRequest) {
  const requestContext = getFrontendAdminRequestContext(request.headers)
  const session = await getServerSession(authOptions)
  if (!session || !hasRole(session.user?.roles ?? [], 'admin')) {
    logFrontendAdminAccessEvent({
      surface: 'admin_api',
      path: ADMIN_ROUTE_PATH,
      method: 'POST',
      outcome: 'forbidden',
      statusCode: 403,
      context: requestContext,
      note: 'missing_admin_session',
    })
    return NextResponse.json({ error: 'Admin privileges required' }, { status: 403 })
  }

  let payload: EnqueuePayload = {}
  try {
    payload = (await request.json()) as EnqueuePayload
  } catch (error) {
    payload = {}
  }

  const symbol = normalizeSymbol(payload.symbol)
  if (!symbol) {
    return NextResponse.json({ error: 'symbol is required' }, { status: 400 })
  }
  const eventId = normalizeOptionalString(payload.eventId)
  const priority = clampPriority(payload.priority)
  const force = payload.force !== undefined ? Boolean(payload.force) : true
  const title = normalizeOptionalString(payload.title)
  const url = normalizeOptionalString(payload.url)
  const rawId = normalizeOptionalString(payload.rawId)

  const params = new URLSearchParams()
  params.set('symbol', symbol)
  params.set('priority', String(priority))
  params.set('force', force ? 'true' : 'false')
  if (eventId) params.set('event_id', eventId)
  if (title) params.set('title', title)
  if (url) params.set('url', url)
  if (rawId) params.set('raw_id', rawId)

  try {
    const response = await proxyServiceJson({
      upstreamPath: '/api/v1/admin/news/queue/enqueue',
      searchParams: params,
      method: 'POST',
    })
    const outcome = response.status < 400 ? 'authorized' : response.status === 403 ? 'forbidden' : 'error'
    logFrontendAdminAccessEvent({
      surface: 'admin_api',
      path: ADMIN_ROUTE_PATH,
      method: 'POST',
      outcome,
      statusCode: response.status,
      context: requestContext,
    })
    return response
  } catch (error) {
    logFrontendAdminAccessEvent({
      surface: 'admin_api',
      path: ADMIN_ROUTE_PATH,
      method: 'POST',
      outcome: 'error',
      statusCode: 500,
      context: requestContext,
      note: 'proxy_exception',
    })
    throw error
  }
}
