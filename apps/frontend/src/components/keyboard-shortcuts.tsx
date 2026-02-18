'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'

const SEARCH_SELECTORS = ['#searchRankings', '#screenerSymbol', '#screenerSymbolMobile', 'input[type="search"]']
const G_SEQUENCE_TIMEOUT = 900

function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  if (el.isContentEditable) return true
  return false
}

function focusSearchInput(): boolean {
  const nodes = Array.from(document.querySelectorAll<HTMLInputElement>(SEARCH_SELECTORS.join(',')))
  for (const input of nodes) {
    if (!input || input.disabled) continue
    if (input.offsetParent === null) continue
    input.focus()
    input.select?.()
    return true
  }
  return false
}

export function KeyboardShortcuts() {
  const router = useRouter()
  const gPendingRef = useRef(false)
  const gTimerRef = useRef<number | null>(null)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      const key = (event.key || '').toLowerCase()
      const hasModifier = event.metaKey || event.ctrlKey || event.altKey

      if (key === 'escape') {
        window.dispatchEvent(new Event('rankalpha:closeOverlays'))
        return
      }

      if (key === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        window.dispatchEvent(new Event('rankalpha:openCommandBar'))
        return
      }

      if (isEditableTarget(event.target)) return

      if (key === '/' && !hasModifier) {
        event.preventDefault()
        if (!focusSearchInput()) {
          window.dispatchEvent(new Event('rankalpha:openCommandBar'))
        }
        return
      }

      if (key === 'g' && !hasModifier) {
        gPendingRef.current = true
        if (gTimerRef.current) window.clearTimeout(gTimerRef.current)
        gTimerRef.current = window.setTimeout(() => {
          gPendingRef.current = false
        }, G_SEQUENCE_TIMEOUT)
        return
      }

      if (gPendingRef.current && !hasModifier) {
        if (key === 'r' || key === 's') {
          event.preventDefault()
          gPendingRef.current = false
          if (gTimerRef.current) window.clearTimeout(gTimerRef.current)
          router.push(key === 'r' ? '/rankings' : '/screener')
        }
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      if (gTimerRef.current) window.clearTimeout(gTimerRef.current)
    }
  }, [router])

  return null
}
