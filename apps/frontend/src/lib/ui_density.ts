import { useEffect, useRef, useState } from 'react'
import { readLocalStorageJson, writeLocalStorageJson } from '@/lib/storage'
import { useMediaQuery } from '@/lib/use_media_query'

export type UiDensity = 'comfortable' | 'dense'

const STORAGE_KEY = 'rankalpha.ui.density.v1'

type PersistedDensity = { v: 1; density: UiDensity }

export function useUiDensity(defaultDensity: UiDensity = 'comfortable') {
  const isMobile = useMediaQuery(
    '(max-width: 767px)',
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 767px)').matches : false
  )
  const [density, setDensityState] = useState<UiDensity>('comfortable')
  const hasInitialized = useRef(false)

  useEffect(() => {
    if (hasInitialized.current) return
    const persisted = readLocalStorageJson<PersistedDensity>(STORAGE_KEY)
    if (persisted?.density === 'dense' || persisted?.density === 'comfortable') {
      setDensityState(persisted.density)
      hasInitialized.current = true
      return
    }
    setDensityState(isMobile ? 'comfortable' : defaultDensity)
    hasInitialized.current = true
  }, [defaultDensity, isMobile])

  const setDensity = (next: UiDensity) => {
    setDensityState(next)
    writeLocalStorageJson(STORAGE_KEY, { v: 1, density: next })
  }

  return {
    density,
    setDensity,
    isDense: density === 'dense',
  }
}
