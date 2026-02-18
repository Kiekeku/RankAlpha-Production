import type { MetadataRoute } from 'next'

import { buildUpstreamUrl } from '@/app/api/_utils/upstream'
import type { AiAnalysisList, GradeLeaderboard } from '@/lib/api'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { slugify } from '@/lib/slug'

export const revalidate = 86400
export const dynamic = 'force-dynamic'
// Note: some platforms (e.g., Vercel) may honor this for serverless function timeouts.
export const maxDuration = 60

const SITEMAP_MAX_SYMBOLS = 500
const SITEMAP_PAGE_SIZE = 500
const SITEMAP_MAX_REQUESTS = 3

function toAbsoluteUrl(siteUrl: string, path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${siteUrl}${normalized}`
}

function safeDate(value?: string): Date | undefined {
  if (!value) return undefined
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return undefined
  return d
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const siteUrl = getCanonicalSiteUrl()
  const now = new Date()

  const entries: MetadataRoute.Sitemap = [
    { url: toAbsoluteUrl(siteUrl, '/'), lastModified: now },
    { url: toAbsoluteUrl(siteUrl, '/rankings'), lastModified: now },
    { url: toAbsoluteUrl(siteUrl, '/screener'), lastModified: now },
    { url: toAbsoluteUrl(siteUrl, '/ai-analysis'), lastModified: now },
    { url: toAbsoluteUrl(siteUrl, '/methodology'), lastModified: now },
    { url: toAbsoluteUrl(siteUrl, '/about'), lastModified: now },
  ]

  try {
    const target = buildUpstreamUrl('/api/v1/screener/styles/meta')
    const res = await fetch(target, {
      next: { revalidate, tags: ['screener', 'screener-styles', 'screeners-sitemap'] },
    })
    if (res.ok) {
      const data = (await res.json()) as { name?: string }[] | null
      const styles = Array.isArray(data) ? data : []
      styles.forEach((style) => {
        const name = (style?.name || '').trim()
        if (!name) return
        const slug = slugify(name)
        if (!slug) return
        entries.push({
          url: toAbsoluteUrl(siteUrl, `/screener/${encodeURIComponent(slug)}`),
          lastModified: now,
        })
      })
    }
  } catch {
    // If the API is down, still serve a sitemap for the static pages.
  }

  try {
    const seen = new Set<string>()
    let requests = 0
    for (
      let skip = 0;
      skip < 50_000 && seen.size < SITEMAP_MAX_SYMBOLS && requests < SITEMAP_MAX_REQUESTS;
      skip += SITEMAP_PAGE_SIZE
    ) {
      requests += 1
      const qs = new URLSearchParams({
        skip: String(skip),
        limit: String(SITEMAP_PAGE_SIZE),
      })
      const target = buildUpstreamUrl('/api/v1/ai-analysis/latest', qs)
      const res = await fetch(target, {
        next: { revalidate, tags: ['ai-analysis', 'ai-analysis-latest', 'ai-analysis-sitemap'] },
      })
      if (!res.ok) break

      const data = (await res.json()) as AiAnalysisList
      const items = data?.items ?? []
      for (const it of items) {
        if (seen.size >= SITEMAP_MAX_SYMBOLS) break
        const symbol = (it?.symbol || '').trim().toUpperCase()
        if (!symbol || seen.has(symbol)) continue
        seen.add(symbol)
        entries.push({
          url: toAbsoluteUrl(siteUrl, `/ai-analysis/${encodeURIComponent(symbol)}`),
          lastModified: safeDate(it?.as_of_date) ?? now,
        })
      }

      if (items.length < SITEMAP_PAGE_SIZE) break
    }
  } catch {
    // If the API is down, still serve a sitemap for the static pages.
  }

  try {
    const seen = new Set<string>()
    let requests = 0
    for (
      let skip = 0;
      skip < 50_000 && seen.size < SITEMAP_MAX_SYMBOLS && requests < SITEMAP_MAX_REQUESTS;
      skip += SITEMAP_PAGE_SIZE
    ) {
      requests += 1
      const qs = new URLSearchParams({
        skip: String(skip),
        limit: String(SITEMAP_PAGE_SIZE),
        sort_by: 'grade',
        sort_order: 'desc',
      })
      const target = buildUpstreamUrl('/api/v1/grading/grades', qs)
      const res = await fetch(target, {
        next: { revalidate, tags: ['grades', 'grade', 'asset', 'rankings', 'rankings-sitemap'] },
      })
      if (!res.ok) break

      const data = (await res.json()) as GradeLeaderboard
      const items = data?.stocks ?? []
      for (const it of items) {
        if (seen.size >= SITEMAP_MAX_SYMBOLS) break
        const symbol = (it?.symbol || '').trim().toUpperCase()
        if (!symbol || seen.has(symbol)) continue
        seen.add(symbol)
        entries.push({
          url: toAbsoluteUrl(siteUrl, `/ticker/${encodeURIComponent(symbol)}`),
          lastModified: safeDate(it?.date) ?? safeDate(data?.as_of_date) ?? now,
        })
      }

      if (items.length < SITEMAP_PAGE_SIZE) break
    }
  } catch {
    // If the API is down, still serve a sitemap for the static pages.
  }

  return entries
}
