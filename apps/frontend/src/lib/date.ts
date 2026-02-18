const EASTERN_TIME_ZONE = 'America/New_York'

export type DateInput = Date | string | number | null | undefined

type EasternParts = Partial<Record<Intl.DateTimeFormatPartTypes, string>>

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function getEasternParts(
  value: DateInput,
  options: Intl.DateTimeFormatOptions
): EasternParts | null {
  const date = toDate(value)
  if (!date) return null
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: EASTERN_TIME_ZONE,
      hour12: false,
      ...options,
    })
    const parts = formatter.formatToParts(date)
    return parts.reduce<EasternParts>((acc, part) => {
      if (part.type !== 'literal') acc[part.type] = part.value
      return acc
    }, {})
  } catch {
    return null
  }
}

function buildIsoDate(parts: EasternParts | null, fallback: string): string {
  if (!parts) return fallback
  const { year, month, day } = parts
  if (!year || !month || !day) return fallback
  return `${year}-${month}-${day}`
}

export function formatEasternDate(value: DateInput, fallback = '-'): string {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
      return trimmed
    }
  }
  const parts = getEasternParts(value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return buildIsoDate(parts, fallback)
}

export function formatEasternMonthDay(value: DateInput, fallback = '-'): string {
  const parts = getEasternParts(value, {
    month: 'short',
    day: '2-digit',
  })
  if (!parts?.month || !parts?.day) return fallback
  const dayNumeric = Number.parseInt(parts.day, 10)
  const day = Number.isNaN(dayNumeric) ? parts.day : String(dayNumeric)
  return `${parts.month} ${day}`
}

export function formatEasternDateTime(
  value: DateInput,
  fallback = '-',
  includeZone = true
): string {
  const parts = getEasternParts(value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
  if (!parts) return fallback
  const date = buildIsoDate(parts, fallback)
  if (date === fallback) return fallback
  const { hour, minute } = parts
  if (!hour || !minute) return fallback
  const time = `${hour}:${minute}`
  const zone = includeZone ? ' ET' : ''
  return `${date} ${time}${zone}`.trim()
}

export function formatEasternTime(
  value: DateInput,
  fallback = '-',
  includeZone = true
): string {
  const parts = getEasternParts(value, {
    hour: '2-digit',
    minute: '2-digit',
  })
  if (!parts) return fallback
  const { hour, minute } = parts
  if (!hour || !minute) return fallback
  const time = `${hour}:${minute}`
  const zone = includeZone ? ' ET' : ''
  return `${time}${zone}`.trim()
}

export { EASTERN_TIME_ZONE }
