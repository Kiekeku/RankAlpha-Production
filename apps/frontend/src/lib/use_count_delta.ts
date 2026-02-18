'use client'

import { useEffect, useRef, useState } from 'react'

export function useCountDeltaBadge(total: number, filterKey: string, opts?: { ttlMs?: number }) {
  const ttlMs = opts?.ttlMs ?? 3500
  const [delta, setDelta] = useState<string | null>(null)
  const pendingPrevTotalRef = useRef<number | null>(null)
  const pendingKeyRef = useRef<string | null>(null)
  const lastKeyRef = useRef<string | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!Number.isFinite(total)) return

    if (lastKeyRef.current == null) {
      lastKeyRef.current = filterKey
      return
    }

    if (filterKey !== lastKeyRef.current) {
      pendingPrevTotalRef.current = total
      pendingKeyRef.current = filterKey
      lastKeyRef.current = filterKey
    }
  }, [filterKey, total])

  useEffect(() => {
    if (!Number.isFinite(total)) return
    if (pendingKeyRef.current !== filterKey) return
    const prev = pendingPrevTotalRef.current
    if (prev == null || !Number.isFinite(prev)) return

    pendingPrevTotalRef.current = null
    pendingKeyRef.current = null

    if (prev === total) return
    setDelta(`${prev.toLocaleString()} → ${total.toLocaleString()}`)

    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => {
      setDelta(null)
    }, ttlMs)
  }, [filterKey, total, ttlMs])

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  return { delta }
}

