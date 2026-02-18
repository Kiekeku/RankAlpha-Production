'use client'

import { useEffect, useState } from 'react'

export function useMediaQuery(query: string, initialState = false): boolean {
  const [matches, setMatches] = useState<boolean>(initialState)

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return

    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)

    onChange()

    if (mql.addEventListener) {
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    }

    mql.addListener(onChange)
    return () => mql.removeListener(onChange)
  }, [query])

  return matches
}

export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 1024px)')
}

