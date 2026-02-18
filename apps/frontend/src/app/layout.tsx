import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { Suspense } from 'react'
import './globals.css'
import { Providers } from '@/components/providers'
import { MainNav } from '@/components/main-nav'
import { Breadcrumbs } from '@/components/breadcrumbs'
import { Toaster } from '@/components/ui/toaster'
import { Footer } from '@/components/footer'
import { GoogleTagManager } from '@/components/google-tag-manager'
import { getCanonicalSiteUrl } from '@/lib/server/site-url'
import { HashRouteRedirect } from '@/components/hash-route-redirect'

const inter = Inter({ subsets: ['latin'] })

const siteUrl = getCanonicalSiteUrl()

const metadataBase = (() => {
  try {
    return new URL(siteUrl)
  } catch {
    return undefined
  }
})()

export const metadata: Metadata = {
  metadataBase,
  title: {
    default: 'RankAlpha',
    template: '%s - RankAlpha',
  },
  description: 'Financial ranking and analysis platform',
  icons: {
    icon: [
      { url: '/favicon.ico' },
      { url: '/favicon-32x32.png', sizes: '32x32', type: 'image/png' },
      { url: '/favicon-16x16.png', sizes: '16x16', type: 'image/png' },
      { url: '/android-chrome-192x192.png', sizes: '192x192', type: 'image/png' },
      { url: '/android-chrome-512x512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [
      { url: '/apple-touch-icon.png', sizes: '180x180', type: 'image/png' },
    ],
    shortcut: ['/favicon.ico'],
  },
}

export default function RootLayout({
  children,
  modal,
}: {
  children: React.ReactNode
  modal: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png" />
        <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/site.webmanifest" />
      </head>
      {/* Initial theme script: default to dark; respect user's saved choice */}
      <body className={inter.className}>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                const stored = localStorage.getItem('theme');
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                const useDark = stored ? (stored === 'dark') : prefersDark; // default to system
                if (useDark) document.documentElement.classList.add('dark');
                else document.documentElement.classList.remove('dark');
              } catch (e) {}
            `,
          }}
        />
        <Suspense fallback={null}>
          <GoogleTagManager />
        </Suspense>
        <Providers>
          <HashRouteRedirect />
          <div className="flex min-h-screen flex-col">
            <MainNav />
            <Suspense fallback={null}>
              <div className="container mx-auto px-4 pt-2">
                <Breadcrumbs />
              </div>
            </Suspense>
            <main className="flex-1 container mx-auto px-4 pt-0 pb-6 sm:pt-0 sm:pb-8">
              {children}
            </main>
            {modal}
            <Footer />
            <Toaster />
          </div>
        </Providers>
      </body>
    </html>
  )
}
