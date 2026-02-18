'use client'

import { useEffect } from 'react'

import { readSessionStorageItem, removeSessionStorageItem } from '@/lib/storage'

const FOCUS_RETURN_ID_KEY = 'rankalpha.focusReturnId'

function elementIsInViewport(el: HTMLElement) {
  const rect = el.getBoundingClientRect()
  const margin = 16
  return rect.top >= margin && rect.bottom <= window.innerHeight - margin
}

export function FocusReturnHandler() {
  useEffect(() => {
    const restore = () => {
      window.setTimeout(() => {
        const id = readSessionStorageItem(FOCUS_RETURN_ID_KEY)
        if (!id) return
        removeSessionStorageItem(FOCUS_RETURN_ID_KEY)
        const el = document.getElementById(id) as HTMLElement | null
        if (!el) return
        try {
          if (!elementIsInViewport(el)) {
            el.scrollIntoView({ block: 'center' })
          }
          el.focus({ preventScroll: true })
        } catch {
          // ignore
        }
      }, 60)
    }

    window.addEventListener('rankalpha:restoreFocus', restore)
    return () => window.removeEventListener('rankalpha:restoreFocus', restore)
  }, [])

  return null
}

