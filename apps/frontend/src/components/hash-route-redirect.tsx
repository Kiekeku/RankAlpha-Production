'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export function HashRouteRedirect() {
  const router = useRouter()

  useEffect(() => {
    if (typeof window === 'undefined') return
    const hash = window.location.hash || ''
    if (!hash.startsWith('#/')) return
    const next = hash.slice(1)
    if (!next || next === '/') return
    router.replace(next)
  }, [router])

  return null
}
