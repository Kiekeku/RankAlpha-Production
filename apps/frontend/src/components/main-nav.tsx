'use client'

import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Menu, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  navigationMenuTriggerStyle,
} from '@/components/ui/navigation-menu'
import { ThemeToggle } from '@/components/theme-toggle'
import { ContextBar } from '@/components/context-bar'
import { UserMenu } from '@/components/user-menu'
import { hasRole } from '@/lib/roles'
import { TickerCommandBar } from '@/components/ticker-command-bar'
import { DataStatusIndicator } from '@/components/data/data-status-indicator'

type NavItem = {
  name: string
  href: string
  matchPath?: string
}

const baseNavigation: NavItem[] = [
  { name: 'Overview', href: '/overview/nowcast', matchPath: '/overview' },
  { name: 'Rankings', href: '/rankings' },
  { name: 'Screener', href: '/screener' },
  { name: 'AI Feed', href: '/ai-analysis' },
  { name: 'About', href: '/about' },
]

export function MainNav() {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)
  const { data: session } = useSession()
  const isAdmin = hasRole(session?.user?.roles ?? [], 'admin')
  const navItems = isAdmin
    ? [...baseNavigation, { name: 'Portfolio', href: '/portfolio' }, { name: 'Admin', href: '/admin' }]
    : baseNavigation
  const startHereHref = '/about#contact'

  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  return (
    <header className="sticky top-0 z-50 w-full bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container relative flex items-center justify-between gap-1.5 py-1.5 md:h-12 md:gap-6 md:py-0">
        <div className="flex items-center gap-1.5 md:mr-4 md:gap-4">
          <Link href="/" className="flex items-center space-x-1.5" aria-label="RankAlpha Home">
            <span suppressHydrationWarning className="flex h-7 w-7 items-center justify-center">
              <Image
                src="/logo.png"
                alt="RankAlpha logo"
                width={28}
                height={28}
                priority
                suppressHydrationWarning
              />
            </span>
            <span className="text-lg font-bold tracking-tight text-primary sm:text-xl">RankAlpha</span>
          </Link>
          <div className="hidden max-w-full overflow-x-auto md:block">
            <NavigationMenu>
              <NavigationMenuList className="flex-nowrap">
                {navItems.map((item) => {
                  const targetPath = item.matchPath ?? item.href
                  const isActive = item.matchPath ? pathname.startsWith(item.matchPath) : pathname === targetPath
                  return (
                    <NavigationMenuItem key={item.href}>
                      <Link href={item.href} legacyBehavior passHref>
                        <NavigationMenuLink
                          className={cn(
                            navigationMenuTriggerStyle(),
                            isActive && 'bg-accent'
                          )}
                        >
                          {item.name}
                        </NavigationMenuLink>
                      </Link>
                    </NavigationMenuItem>
                  )
                })}
              </NavigationMenuList>
            </NavigationMenu>
          </div>
          <Link
            href={startHereHref}
            className="ml-1 hidden items-center gap-1 rounded-full border border-outline/10 bg-card px-3 py-1 text-[11px] font-semibold text-muted-foreground transition hover:border-outline/20 hover:text-foreground md:inline-flex"
          >
            Start here
          </Link>
        </div>
        <div className="flex items-center gap-1.5 md:ml-auto">
          <TickerCommandBar className="inline-flex" />
          <DataStatusIndicator className="hidden md:inline-flex" />
          <div className="hidden md:block">
            <ThemeToggle />
          </div>
          <div className="hidden md:block">
            <UserMenu />
          </div>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-md border px-2 py-1 text-sm font-medium md:hidden"
            aria-label="Toggle navigation menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((open) => !open)}
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
        {mobileOpen && (
          <nav className="absolute left-0 right-0 top-full z-40 mt-2 space-y-1 rounded-md border bg-background p-2 shadow-lg md:hidden">
            {navItems.map((item) => {
              const targetPath = item.matchPath ?? item.href
              const isActive = item.matchPath ? pathname.startsWith(item.matchPath) : pathname === targetPath
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'block rounded-md px-3 py-2 text-sm font-medium hover:bg-accent',
                    isActive ? 'bg-accent text-accent-foreground' : 'text-foreground'
                  )}
                >
                  {item.name}
                </Link>
              )
            })}
            <Link
              href={startHereHref}
              className="block rounded-md px-3 py-2 text-xs font-semibold text-muted-foreground hover:bg-accent"
            >
              Start here
            </Link>
            <div className="mt-2 space-y-2 border-t border-border/60 pt-2">
              <DataStatusIndicator className="w-full justify-start" />
              <UserMenu variant="mobile" />
              <ThemeToggle variant="menu" />
            </div>
          </nav>
        )}
      </div>
      <ContextBar />
    </header>
  )
}
