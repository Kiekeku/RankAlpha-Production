'use client'

import type { ReactNode } from 'react'

import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

import { cn } from '@/lib/utils'
import { DocsSearch } from '@/components/docs/docs-search'

export type DocsTocItem = {
  id: string
  label: string
}

export function DocsLayout({
  title,
  subtitle,
  toc,
  children,
  backHref = '/about',
  backLabel = 'Back to About overview',
  showSearch = true,
}: {
  title: string
  subtitle?: string
  toc: DocsTocItem[]
  children: ReactNode
  backHref?: string
  backLabel?: string
  showSearch?: boolean
}) {
  return (
    <div className="space-y-6 sm:space-y-8">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <ArrowLeft className="h-4 w-4" />
        <Link href={backHref} className="text-primary hover:underline">
          {backLabel}
        </Link>
      </div>

      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        {subtitle ? <p className="text-sm text-muted-foreground">{subtitle}</p> : null}
      </div>

      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-24 lg:h-[calc(100dvh-7rem)] lg:overflow-auto">
          <div className="space-y-3">
            {showSearch ? <DocsSearch /> : null}
            <nav aria-label="On this page" className="rounded-2xl border border-outline/10 bg-card p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">On this page</div>
              <div className="mt-2 space-y-1 text-sm">
                {toc.map((item) => (
                  <a
                    key={item.id}
                    href={`#${item.id}`}
                    className={cn(
                      'block rounded-lg px-2 py-1 font-semibold text-muted-foreground transition',
                      'hover:bg-secondary/10 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    )}
                  >
                    {item.label}
                  </a>
                ))}
              </div>
            </nav>
          </div>
        </aside>

        <main className="space-y-6">{children}</main>
      </div>
    </div>
  )
}
