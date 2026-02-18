import { NextRequest } from 'next/server'
import { getToken } from 'next-auth/jwt'

export async function buildAuthHeaders(request: NextRequest, initHeaders?: HeadersInit): Promise<Headers> {
  const headers = new Headers(initHeaders)
  const rawToken = await getToken({ req: request, secret: process.env.NEXTAUTH_SECRET, raw: true })
  if (rawToken) {
    headers.set('Authorization', `Bearer ${rawToken}`)
  }
  return headers
}
