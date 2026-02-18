const RETURN_TO_KEY = 'rankalpha.ticker.returnTo'
const ORIGIN_KEY = 'rankalpha.ticker.origin'

export type TickerOrigin = 'rankings' | 'screener' | 'ai-analysis' | 'compare' | 'command' | 'unknown'

export function inferTickerOrigin(pathname: string): TickerOrigin {
  const path = (pathname || '').trim()
  if (path.startsWith('/rankings')) return 'rankings'
  if (path.startsWith('/screener')) return 'screener'
  if (path.startsWith('/ai-analysis')) return 'ai-analysis'
  if (path.startsWith('/compare')) return 'compare'
  return 'unknown'
}

export function rememberTickerOrigin(origin: TickerOrigin, returnTo?: string) {
  if (typeof window === 'undefined') return
  try {
    const href = returnTo ?? `${window.location.pathname}${window.location.search}`
    window.localStorage.setItem(RETURN_TO_KEY, href)
    window.localStorage.setItem(ORIGIN_KEY, origin)
  } catch {
    // ignore storage failures
  }
}

export function readTickerOrigin(): { origin: TickerOrigin; returnTo: string | null } {
  if (typeof window === 'undefined') return { origin: 'unknown', returnTo: null }
  try {
    const originRaw =
      window.localStorage.getItem(ORIGIN_KEY) ||
      window.sessionStorage.getItem(ORIGIN_KEY) ||
      'unknown'
    const origin = (originRaw || 'unknown') as TickerOrigin
    const returnTo =
      window.localStorage.getItem(RETURN_TO_KEY) ||
      window.sessionStorage.getItem(RETURN_TO_KEY)
    return { origin, returnTo }
  } catch {
    return { origin: 'unknown', returnTo: null }
  }
}
