import 'server-only'

import { headers } from 'next/headers'
import { getServerSession } from 'next-auth'
import { redirect } from 'next/navigation'
import type { Session } from 'next-auth'

import { authOptions } from '@/lib/auth'
import { hasRole } from '@/lib/roles'
import {
  FrontendAdminSurface,
  getFrontendAdminRequestContext,
  inferAdminPathFromHeaders,
  logFrontendAdminAccessEvent,
  shouldLogAuthorizedAdminAccess,
} from '@/lib/server/admin_security_log'

type RequireAdminSessionOptions = {
  attemptedPath?: string
  method?: string
  surface?: FrontendAdminSurface
}

export async function requireAdminSession(
  redirectTo = '/',
  options: RequireAdminSessionOptions = {}
): Promise<Session> {
  const requestHeaders = headers()
  const context = getFrontendAdminRequestContext(requestHeaders)
  const attemptedPath = options.attemptedPath || inferAdminPathFromHeaders(requestHeaders) || 'unknown'
  const method = options.method || 'GET'
  const surface = options.surface || 'admin_page'

  const session = await getServerSession(authOptions)
  if (!session || !hasRole(session.user?.roles ?? [], 'admin')) {
    logFrontendAdminAccessEvent({
      surface,
      path: attemptedPath,
      method,
      outcome: 'unauthorized',
      statusCode: 307,
      context,
      note: 'missing_admin_session',
    })
    redirect(redirectTo)
  }

  if (shouldLogAuthorizedAdminAccess()) {
    logFrontendAdminAccessEvent({
      surface,
      path: attemptedPath,
      method,
      outcome: 'authorized',
      statusCode: 200,
      context,
    })
  }
  return session as Session
}
