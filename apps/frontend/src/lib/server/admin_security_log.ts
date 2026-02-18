import 'server-only'

type HeaderReader = {
  get(name: string): string | null | undefined
}

export type FrontendAdminSurface = 'admin_page' | 'admin_api'
export type FrontendAdminOutcome = 'authorized' | 'unauthorized' | 'forbidden' | 'error'
export type FrontendClientClass = 'bot' | 'browser' | 'other' | 'unknown'

export type FrontendAdminRequestContext = {
  clientIp: string
  clientClass: FrontendClientClass
  userAgent: string
}

const BOT_UA_TOKENS = [
  'bot',
  'crawler',
  'crawl',
  'spider',
  'scrapy',
  'slurp',
  'headless',
  'python-requests',
  'python-httpx',
  'aiohttp',
  'okhttp',
  'go-http-client',
  'curl/',
  'wget/',
]

const BROWSER_UA_TOKENS = ['mozilla/', 'chrome/', 'safari/', 'firefox/', 'edg/']

function envBool(name: string, fallback: boolean): boolean {
  const raw = (process.env[name] || '').trim().toLowerCase()
  if (!raw) return fallback
  return ['1', 'true', 'yes', 'on'].includes(raw)
}

function envInt(name: string, fallback: number): number {
  const raw = (process.env[name] || '').trim()
  if (!raw) return fallback
  const value = Number.parseInt(raw, 10)
  if (!Number.isFinite(value) || value < 0) return fallback
  return value
}

const SECURITY_LOG_ENABLED = envBool('FRONTEND_ADMIN_SECURITY_LOG_ENABLED', true)
const SECURITY_LOG_AUTHORIZED = envBool('FRONTEND_ADMIN_SECURITY_LOG_AUTHORIZED', false)
const SECURITY_LOG_INCLUDE_USER_AGENT = envBool('FRONTEND_ADMIN_SECURITY_LOG_INCLUDE_USER_AGENT', false)
const SECURITY_LOG_QUEUE_MAX = envInt('FRONTEND_ADMIN_SECURITY_LOG_QUEUE_MAX', 5000)
const SECURITY_LOG_BATCH_SIZE = Math.max(1, envInt('FRONTEND_ADMIN_SECURITY_LOG_BATCH_SIZE', 200))
const SECURITY_LOG_FLUSH_MS = Math.max(100, envInt('FRONTEND_ADMIN_SECURITY_LOG_FLUSH_MS', 1000))

const LOG_QUEUE: string[] = []
let dropCount = 0
let flushTimer: NodeJS.Timeout | null = null

function firstIp(value: string): string {
  const first = value.split(',')[0]?.trim() || ''
  if (!first) return ''
  const mapped = first.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/i)
  return mapped ? mapped[1] : first
}

function classifyClient(userAgent: string): FrontendClientClass {
  const ua = userAgent.trim().toLowerCase()
  if (!ua) return 'unknown'
  if (BOT_UA_TOKENS.some((token) => ua.includes(token))) return 'bot'
  if (BROWSER_UA_TOKENS.some((token) => ua.includes(token))) return 'browser'
  return 'other'
}

function sanitizePath(path: string): string {
  const raw = (path || '').trim()
  if (!raw) return 'unknown'
  try {
    if (raw.startsWith('http://') || raw.startsWith('https://')) {
      return new URL(raw).pathname || 'unknown'
    }
  } catch {
    // fall through to raw string handling
  }
  const withoutHash = raw.split('#')[0] || raw
  const withoutQuery = withoutHash.split('?')[0] || withoutHash
  return withoutQuery || 'unknown'
}

function safeMethod(method: string | undefined): string {
  const normalized = (method || 'GET').trim().toUpperCase()
  if (!normalized) return 'GET'
  return normalized.slice(0, 16)
}

function enqueueLine(line: string): void {
  if (LOG_QUEUE.length >= SECURITY_LOG_QUEUE_MAX) {
    dropCount += 1
    return
  }
  LOG_QUEUE.push(line)
  scheduleFlush()
}

function flushQueue(): void {
  flushTimer = null
  if (!LOG_QUEUE.length && !dropCount) return

  const batch = LOG_QUEUE.splice(0, SECURITY_LOG_BATCH_SIZE)
  if (dropCount > 0) {
    batch.unshift(
      JSON.stringify({
        ts: new Date().toISOString(),
        event: 'frontend_admin_access_log_dropped',
        dropped: dropCount,
      })
    )
    dropCount = 0
  }

  const payload = `${batch.join('\n')}\n`
  setImmediate(() => {
    try {
      process.stdout.write(payload)
    } catch {
      // best-effort logging only
    }
  })

  if (LOG_QUEUE.length || dropCount) {
    scheduleFlush()
  }
}

function scheduleFlush(): void {
  if (flushTimer) return
  flushTimer = setTimeout(flushQueue, SECURITY_LOG_FLUSH_MS)
  flushTimer.unref?.()
}

export function shouldLogAuthorizedAdminAccess(): boolean {
  return SECURITY_LOG_AUTHORIZED
}

export function getFrontendAdminRequestContext(headers: HeaderReader): FrontendAdminRequestContext {
  const xForwardedFor = headers.get('x-forwarded-for') || ''
  const xRealIp = headers.get('x-real-ip') || ''
  const cfConnectingIp = headers.get('cf-connecting-ip') || ''
  const clientIp = firstIp(xForwardedFor) || firstIp(xRealIp) || firstIp(cfConnectingIp) || '-'
  const userAgent = (headers.get('user-agent') || '').trim()
  return {
    clientIp,
    clientClass: classifyClient(userAgent),
    userAgent,
  }
}

export function inferAdminPathFromHeaders(headers: HeaderReader): string | null {
  const candidates = [
    headers.get('next-url'),
    headers.get('x-forwarded-uri'),
    headers.get('x-original-uri'),
    headers.get('referer'),
  ]
  for (const candidate of candidates) {
    const normalized = sanitizePath(candidate || '')
    if (normalized.startsWith('/admin') || normalized.startsWith('/api/admin')) {
      return normalized
    }
  }
  return null
}

export function logFrontendAdminAccessEvent(args: {
  surface: FrontendAdminSurface
  path: string
  method?: string
  outcome: FrontendAdminOutcome
  statusCode: number
  context: FrontendAdminRequestContext
  note?: string
}): void {
  if (!SECURITY_LOG_ENABLED) return
  if (args.outcome === 'authorized' && !SECURITY_LOG_AUTHORIZED) return

  const payload: Record<string, unknown> = {
    ts: new Date().toISOString(),
    event: 'frontend_admin_access',
    surface: args.surface,
    path: sanitizePath(args.path),
    method: safeMethod(args.method),
    outcome: args.outcome,
    status_code: args.statusCode,
    client_ip: args.context.clientIp,
    client_class: args.context.clientClass,
  }

  if (SECURITY_LOG_INCLUDE_USER_AGENT && args.context.userAgent) {
    payload.user_agent = args.context.userAgent.slice(0, 512)
  }
  if (args.note) {
    payload.note = args.note.slice(0, 256)
  }

  enqueueLine(JSON.stringify(payload))
}
