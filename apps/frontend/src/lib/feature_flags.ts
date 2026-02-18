const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on'])
const FALSE_VALUES = new Set(['0', 'false', 'no', 'off'])

function readBooleanEnv(raw: string | undefined | null, defaultValue: boolean): boolean {
  if (raw == null) return defaultValue
  const normalized = raw.trim().toLowerCase()
  if (!normalized) return defaultValue
  if (TRUE_VALUES.has(normalized)) return true
  if (FALSE_VALUES.has(normalized)) return false
  return defaultValue
}

export const SHOW_RAW_DATA = readBooleanEnv(
  process.env.NEXT_PUBLIC_SHOW_RAW_DATA ?? process.env.SHOW_RAW_DATA,
  true,
)
