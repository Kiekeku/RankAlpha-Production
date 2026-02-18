'use client'

import { useEffect, useRef, useState } from 'react'
import { SparklineMini } from '@/features/regime/regime-shared'

export function ResponsiveSparklineMini(
  props: Omit<Parameters<typeof SparklineMini>[0], 'width'> & { maxWidth?: number; minWidth?: number }
) {
  const { maxWidth = 220, minWidth = 140, ...rest } = props
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(maxWidth)

  useEffect(() => {
    if (!ref.current || typeof ResizeObserver === 'undefined') return
    const el = ref.current
    const observer = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0]?.contentRect?.width ?? 0)
      if (!next) return
      const clamped = Math.max(minWidth, Math.min(maxWidth, next))
      setWidth((prev) => (prev === clamped ? prev : clamped))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [maxWidth, minWidth])

  return (
    <div ref={ref} className="w-full min-w-0">
      <SparklineMini {...rest} width={width} />
    </div>
  )
}
