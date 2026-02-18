import { NextRequest, NextResponse } from 'next/server'

import {
  getFrontendAdminRequestContext,
  logFrontendAdminAccessEvent,
} from '@/lib/server/admin_security_log'

export const runtime = 'nodejs'

function logUnknownAdminApi(request: NextRequest, method: string): void {
  logFrontendAdminAccessEvent({
    surface: 'admin_api',
    path: request.nextUrl.pathname,
    method,
    outcome: 'forbidden',
    statusCode: 404,
    context: getFrontendAdminRequestContext(request.headers),
    note: 'unknown_admin_api_route',
  })
}

function notFoundResponse(): NextResponse {
  return NextResponse.json({ error: 'Not found' }, { status: 404 })
}

export async function GET(request: NextRequest) {
  logUnknownAdminApi(request, 'GET')
  return notFoundResponse()
}

export async function POST(request: NextRequest) {
  logUnknownAdminApi(request, 'POST')
  return notFoundResponse()
}

export async function PUT(request: NextRequest) {
  logUnknownAdminApi(request, 'PUT')
  return notFoundResponse()
}

export async function PATCH(request: NextRequest) {
  logUnknownAdminApi(request, 'PATCH')
  return notFoundResponse()
}

export async function DELETE(request: NextRequest) {
  logUnknownAdminApi(request, 'DELETE')
  return notFoundResponse()
}

export async function OPTIONS(request: NextRequest) {
  logUnknownAdminApi(request, 'OPTIONS')
  return notFoundResponse()
}
