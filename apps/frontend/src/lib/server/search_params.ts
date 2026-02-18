import 'server-only'

export type ServerSearchParams = Record<string, string | string[] | undefined>

export function getFirstSearchParam(searchParams: ServerSearchParams | undefined, key: string): string | undefined {
  const value = searchParams?.[key]
  if (Array.isArray(value)) return value[0]
  return value
}

export function getFirstSearchParamTrimmed(searchParams: ServerSearchParams | undefined, key: string): string | undefined {
  const value = getFirstSearchParam(searchParams, key)
  const trimmed = value?.trim()
  return trimmed ? trimmed : undefined
}

export function getIntSearchParam(
  searchParams: ServerSearchParams | undefined,
  key: string,
  opts: { min?: number; max?: number } = {},
): number | undefined {
  const raw = getFirstSearchParamTrimmed(searchParams, key)
  if (!raw) return undefined
  const parsed = Number.parseInt(raw, 10)
  if (!Number.isFinite(parsed)) return undefined
  const min = typeof opts.min === 'number' ? opts.min : -Infinity
  const max = typeof opts.max === 'number' ? opts.max : Infinity
  return Math.max(min, Math.min(max, parsed))
}

