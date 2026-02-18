import Link from 'next/link'

import { cn } from '@/lib/utils'
import { buildFreshnessLabel } from '@/components/data/data-freshness'

type DataFooterLink = {
  label: string
  href: string
}

export function DataFooter({
  asOf,
  source,
  cadence,
  links,
  className,
}: {
  asOf?: string | null
  source?: string
  cadence?: string
  links?: DataFooterLink[]
  className?: string
}) {
  const parts = [
    buildFreshnessLabel(asOf ?? null, cadence ?? null),
    source ? `Source: ${source}` : null,
  ].filter(Boolean) as string[]

  return (
    <div
      className={cn(
        'mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-outline/10 pt-2 text-[11px] text-muted-foreground',
        className,
      )}
    >
      <span className="flex flex-wrap items-center gap-2">
        {parts.map((part, idx) => (
          <span key={`${part}-${idx}`} className="inline-flex items-center gap-2">
            <span>{part}</span>
            {idx < parts.length - 1 ? <span aria-hidden="true">·</span> : null}
          </span>
        ))}
      </span>
      {links && links.length ? (
        <span className="inline-flex items-center gap-3">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="font-semibold text-muted-foreground transition hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </span>
      ) : null}
    </div>
  )
}
