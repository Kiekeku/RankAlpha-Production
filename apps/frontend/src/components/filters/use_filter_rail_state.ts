'use client'

import { useCallback, useEffect, useState } from 'react'

import { readLocalStorageJson, writeLocalStorageJson } from '@/lib/storage'

export function useFilterRailState(storageKey: string, defaultCollapsed = false) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  useEffect(() => {
    const persisted = readLocalStorageJson<boolean>(storageKey)
    if (typeof persisted === 'boolean') {
      setCollapsed(persisted)
    }
  }, [storageKey])

  useEffect(() => {
    writeLocalStorageJson(storageKey, collapsed)
  }, [collapsed, storageKey])

  const toggle = useCallback(() => {
    setCollapsed((prev) => !prev)
  }, [])

  return { collapsed, setCollapsed, toggle }
}
