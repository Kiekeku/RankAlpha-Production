'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { SearchIcon } from 'lucide-react'

import { DOCS_INDEX } from '@/content/docs_index'
import { cn } from '@/lib/utils'

type DocsSearchResult = {
  key: string
  title: string
  href: string
  snippet: string
}

function normalize(value: string) {
  return value.trim().toLowerCase()
}

function buildResults(query: string): DocsSearchResult[] {
  const q = normalize(query)
  if (!q) return []
  const results: DocsSearchResult[] = []

  DOCS_INDEX.forEach((page) => {
    const titleMatch = normalize(page.title).includes(q)
    const descMatch = normalize(page.description).includes(q)

    if (titleMatch || descMatch) {
      results.push({
        key: `page:${page.href}`,
        title: page.title,
        href: page.href,
        snippet: page.description,
      })
    }

    page.headings.forEach((heading) => {
      if (!normalize(heading.label).includes(q)) return
      results.push({
        key: `heading:${page.href}#${heading.id}`,
        title: `${page.title} · ${heading.label}`,
        href: `${page.href}#${heading.id}`,
        snippet: heading.snippet ?? page.description,
      })
    })
  })

  return results.slice(0, 8)
}

export function DocsSearch({ className }: { className?: string }) {
  const [query, setQuery] = useState('')
  const results = useMemo(() => buildResults(query), [query])

  return (
    <div className={cn('space-y-3', className)}>
      <div className="rounded-2xl border border-outline/10 bg-secondary/10 p-3">
        <div className="flex items-center gap-2">
          <SearchIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search docs and headings…"
            aria-label="Search docs"
            className="h-9 w-full rounded-md border border-outline/10 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <div className="mt-2 text-xs text-muted-foreground">
          Search methodology, glossary, and architecture docs.
        </div>
      </div>

      {query.trim().length ? (
        results.length ? (
          <div className="grid gap-2">
            {results.map((result) => (
              <Link
                key={result.key}
                href={result.href}
                className="group rounded-xl border border-outline/10 bg-card px-3 py-2 text-left transition hover:border-outline/16"
              >
                <div className="text-sm font-semibold text-foreground group-hover:text-primary">{result.title}</div>
                <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{result.snippet}</div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-outline/12 bg-secondary/10 p-3 text-xs text-muted-foreground">
            No matching docs. Try “Momentum”, “Chop”, or “Pipeline”.
          </div>
        )
      ) : null}
    </div>
  )
}
