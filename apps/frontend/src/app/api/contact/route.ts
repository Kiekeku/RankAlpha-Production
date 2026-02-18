import { NextRequest, NextResponse } from 'next/server'
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// Simple in-memory rate limiter (per process)
const buckets = new Map<string, { count: number; resetAt: number }>()
const WINDOW_MS = 60_000
const LIMIT = 5

function rateLimit(key: string) {
  const now = Date.now()
  const b = buckets.get(key)
  if (!b || now > b.resetAt) {
    buckets.set(key, { count: 1, resetAt: now + WINDOW_MS })
    return true
  }
  if (b.count >= LIMIT) return false
  b.count += 1
  return true
}

async function verifyTurnstile(token: string, ip: string | null) {
  const secret = process.env.TURNSTILE_SECRET_KEY
  if (!secret) return false
  try {
    const form = new URLSearchParams()
    form.set('secret', secret)
    form.set('response', token)
    if (ip) form.set('remoteip', ip)
    const res = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST',
      body: form,
    })
    const data = await res.json()
    return !!data?.success
  } catch {
    return false
  }
}

import { buildUpstreamUrl } from '../_utils/upstream'

async function sendEmail({ name, email, message }: { name: string; email: string; message: string }) {
  const subject = `Contact form: ${name}`
  const text = `From: ${name} <${email}>\n\n${message}`
  // Always send via backend ops/email (centralized SMTP/Gmail)
  const url = buildUpstreamUrl('/api/v1/ops/email')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const rawToken = (process.env.AUTH_SERVICE_TOKEN || '').trim()
  const token = rawToken.startsWith('Bearer ') ? rawToken.slice('Bearer '.length).trim() : rawToken
  if (!token) {
    throw new Error('AUTH_SERVICE_TOKEN not configured')
  }
  headers['X-RA-Service-Token'] = token
  const toEnv = (process.env.CONTACT_TO || '').trim()
  const fromEnv = (process.env.CONTACT_FROM || '').trim()
  const payload: Record<string, any> = { subject, text }
  if (toEnv) payload.to = [toEnv]
  if (fromEnv) payload.sender = fromEnv
  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    cache: 'no-store',
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`Backend email failed: ${res.status} ${body?.slice(0, 200)}`)
  }
  return true
}

// no-op (legacy helper removed)

export async function POST(req: NextRequest) {
  const ip = (req.headers.get('x-forwarded-for') || '').split(',')[0]?.trim() || null
  const key = ip || 'anon'
  if (!rateLimit(key)) {
    return NextResponse.json({ error: 'Too many requests' }, { status: 429 })
  }

  const { name, email, message, website, token } = await req.json().catch(() => ({}))
  if (typeof name !== 'string' || typeof email !== 'string' || typeof message !== 'string') {
    return NextResponse.json({ error: 'Invalid payload' }, { status: 400 })
  }
  if ((website || '').length > 0) {
    return NextResponse.json({ ok: true }) // honeypot triggered; pretend success
  }

  if ((name.length < 1 || name.length > 200) || (email.length < 3 || email.length > 320) || (message.length < 5 || message.length > 5000)) {
    return NextResponse.json({ error: 'Invalid field lengths' }, { status: 400 })
  }

  // Verify Turnstile if configured
  if (process.env.TURNSTILE_SECRET_KEY) {
    if (!token || !(await verifyTurnstile(token, ip))) {
      return NextResponse.json({ error: 'Captcha verification failed' }, { status: 400 })
    }
  }

  try {
    await sendEmail({ name, email, message })
    return NextResponse.json({ ok: true })
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e || 'Send failed') }, { status: 500 })
  }
}
