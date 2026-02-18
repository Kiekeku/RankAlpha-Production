import { NextResponse } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  // Disabled by default. Enable temporarily by setting CONTACT_DEBUG=true.
  if (process.env.CONTACT_DEBUG !== 'true') {
    return NextResponse.json({ error: 'Not Found' }, { status: 404 })
  }

  const xfwd = request.headers.get('x-forwarded-for') || ''
  const xreal = request.headers.get('x-real-ip') || ''
  const rawIp = (xfwd.split(',')[0] || '').trim() || xreal.trim() || ''
  const v4mapped = rawIp.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/i)
  const ip = v4mapped ? v4mapped[1] : rawIp
  const localhostAllowed = ip === '127.0.0.1' || ip === '::1'
  if (!localhostAllowed) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const resp = {
    nodeEnv: process.env.NODE_ENV,
    contact: {
      backendEmail: true,
      adminTokenSet: !!process.env.AUTH_SERVICE_TOKEN,
      from: process.env.CONTACT_FROM || '(unset)',
      to: process.env.CONTACT_TO || '(unset)',
    },
    debug: {
      turnstileSite: process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ? 'set' : 'unset',
      turnstileSecret: process.env.TURNSTILE_SECRET_KEY ? 'set' : 'unset',
    },
  }
  return NextResponse.json(resp)
}
