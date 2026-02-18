export function cloneSearchParams(searchParams: URLSearchParams): URLSearchParams {
  return new URLSearchParams(searchParams.toString())
}

export function isTruthySearchParam(searchParams: URLSearchParams, key: string): boolean {
  const raw = (searchParams.get(key) || '').trim().toLowerCase()
  return raw === '1' || raw === 'true' || raw === 'yes'
}

export function buildPathWithSearchParams(pathname: string, searchParams: URLSearchParams): string {
  const qs = searchParams.toString()
  return qs ? `${pathname}?${qs}` : pathname
}

