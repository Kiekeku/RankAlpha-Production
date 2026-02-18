import Link from 'next/link'

import { cn } from '@/lib/utils'

type NavItem = {
  label: string
  href: string
}

type NavGroup = {
  label: string
  items: NavItem[]
}

export function TickerSectionNav({
  groups,
  tabs,
  className,
  activeHref,
  backToTop,
}: {
  groups: NavGroup[]
  tabs?: Array<{ label: string; href: string; active?: boolean }>
  className?: string
  activeHref?: string
  backToTop?: { href: string; label?: string }
}) {
  const hasTabs = Array.isArray(tabs) && tabs.length > 0
  return (
    <nav
      className={cn(
        'rounded-2xl border border-outline/10 bg-card/90 p-4 text-sm shadow-sm backdrop-blur',
        className
      )}
      aria-label="On this page"
    >
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">On this page</div>
      <div className="mt-3 space-y-3">
        {hasTabs ? (
          <div className="space-y-1">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Tabs
            </div>
            <div className="space-y-1">
              {tabs!.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'block text-sm transition',
                    item.active ? 'font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
        ) : null}
        {groups.map((group) => (
          <div key={group.label} className="space-y-1">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {group.label}
            </div>
            <div className="space-y-1">
              {group.items.map((item) => {
                const isHash = item.href.startsWith('#')
                const isActive = activeHref === item.href
                const classes = cn(
                  'block border-l border-outline/10 pl-3 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                  isActive ? 'border-primary/60 font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
                )
                return isHash ? (
                  <a key={item.href} href={item.href} className={classes}>
                    {item.label}
                  </a>
                ) : (
                  <Link key={item.href} href={item.href} className={classes}>
                    {item.label}
                  </Link>
                )
              })}
            </div>
          </div>
        ))}
        {backToTop ? (
          <div className="pt-1">
            <a
              href={backToTop.href}
              className="inline-flex items-center gap-1 text-xs font-semibold text-muted-foreground transition hover:text-foreground"
            >
              {backToTop.label ?? 'Back to top'}
            </a>
          </div>
        ) : null}
      </div>
    </nav>
  )
}
