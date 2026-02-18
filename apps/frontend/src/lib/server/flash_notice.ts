import 'server-only'

import { redirect } from 'next/navigation'

import { getFirstSearchParam } from '@/lib/server/search_params'

export type FlashNoticeStatus = 'success' | 'error'

export type FlashNotice = {
  status: FlashNoticeStatus
  message: string
}

export function parseFlashNotice(searchParams?: Record<string, string | string[] | undefined>): FlashNotice | null {
  const status = getFirstSearchParam(searchParams, 'notice')
  const message = getFirstSearchParam(searchParams, 'message')
  if (!status || (status !== 'success' && status !== 'error') || !message) return null
  try {
    return { status, message: decodeURIComponent(message) }
  } catch {
    return { status, message }
  }
}

export function buildFlashRedirectUrl(opts: {
  pathname: string
  status: FlashNoticeStatus
  message: string
  extraParams?: Record<string, string | null | undefined>
}): string {
  const params = new URLSearchParams({
    notice: opts.status,
    message: opts.message.slice(0, 300),
  })

  if (opts.extraParams) {
    Object.entries(opts.extraParams).forEach(([key, value]) => {
      if (typeof value === 'string' && value.trim().length > 0) {
        params.set(key, value)
      }
    })
  }

  const qs = params.toString()
  return qs ? `${opts.pathname}?${qs}` : opts.pathname
}

export function redirectWithFlashNotice(opts: {
  pathname: string
  status: FlashNoticeStatus
  message: string
  extraParams?: Record<string, string | null | undefined>
}): never {
  redirect(buildFlashRedirectUrl(opts))
}

