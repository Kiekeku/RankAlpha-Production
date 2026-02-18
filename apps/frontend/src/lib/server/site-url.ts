function stripTrailingSlash(url: string): string {
  return url.replace(/\/$/, '')
}

let warnedMissingCanonicalBase = false

function inProduction(): boolean {
  return process.env.NODE_ENV === 'production'
}

function inVercel(): boolean {
  const marker = (process.env.VERCEL || '').trim()
  const env = (process.env.VERCEL_ENV || '').trim()
  return marker === '1' || Boolean(env)
}

function inVercelProd(): boolean {
  if (!inVercel()) return false
  const env = (process.env.VERCEL_ENV || '').trim().toLowerCase()
  return !env || env === 'production'
}

/**
 * Canonical site URL for metadata/sitemaps.
 *
 * In production, strongly prefer setting `NEXT_PUBLIC_SITE_URL` (or `NEXTAUTH_URL`) so canonicals/sitemaps never point at localhost.
 */
export function getCanonicalSiteUrl(): string {
  const publicSiteUrl = (process.env.NEXT_PUBLIC_SITE_URL || '').trim()
  if (publicSiteUrl) return stripTrailingSlash(publicSiteUrl)

  const nextAuthUrl = (process.env.NEXTAUTH_URL || '').trim()
  if (nextAuthUrl) return stripTrailingSlash(nextAuthUrl)

  if (inProduction() && inVercelProd()) {
    // Avoid hard-failing builds in non-Vercel environments, but keep Vercel production strict by default.
    // In Vercel prod, missing a canonical base almost always means you'll leak localhost into metadata.
    throw new Error(
      'Missing `NEXT_PUBLIC_SITE_URL` (or `NEXTAUTH_URL`) in Vercel production. Set one to ensure canonicals/sitemaps never point at localhost.',
    )
  }

  const vercelUrl = (process.env.VERCEL_URL || '').trim()
  if (vercelUrl) {
    const normalized = vercelUrl.replace(/\/$/, '')
    if (normalized.startsWith('http://') || normalized.startsWith('https://')) return normalized
    return `https://${normalized}`
  }

  if (inProduction()) {
    if (!warnedMissingCanonicalBase) {
      warnedMissingCanonicalBase = true
      // eslint-disable-next-line no-console
      console.warn(
        'Missing `NEXT_PUBLIC_SITE_URL` / `NEXTAUTH_URL`; falling back to http://localhost:3000 for canonicals/sitemaps.',
      )
    }
  }

  return 'http://localhost:3000'
}
