import { cn } from '@/lib/utils'

export function MiniSparkline({
  values,
  width = 90,
  height = 24,
  className,
}: {
  values?: number[]
  width?: number
  height?: number
  className?: string
}) {
  if (!values || values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1e-6
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width
    const y = height - ((v - min) / span) * height
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const last = values[values.length - 1]
  const mid = (min + max) / 2
  const color = last >= mid ? 'hsl(var(--status-success))' : 'hsl(var(--status-danger))'

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn('block', className)}
      aria-hidden
    >
      <polyline fill="none" stroke={color} strokeWidth="2" points={pts} />
    </svg>
  )
}
