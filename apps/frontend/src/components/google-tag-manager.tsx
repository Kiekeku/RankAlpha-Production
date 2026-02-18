'use client'

import { useEffect, useRef } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'
import Script from 'next/script'

const GTM_ID = (process.env.NEXT_PUBLIC_GTM_ID || '').trim()

declare global {
  interface Window {
    dataLayer: Array<Record<string, unknown>>
  }
}

export function GoogleTagManager() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const search = searchParams?.toString() ?? ''
  const previousUrl = useRef<string | null>(null)

  useEffect(() => {
    if (!GTM_ID) {
      return
    }

    if (typeof window === 'undefined' || !pathname) {
      return
    }

    const pagePath = search ? `${pathname}?${search}` : pathname
    const pageLocation = `${window.location.origin}${pagePath}`

    const push = () => {
      const pageTitle = document.title

      window.dataLayer = window.dataLayer || []
      window.dataLayer.push({
        event: 'gtm.historyChange-v2',
        'gtm.oldUrl': previousUrl.current,
        'gtm.newUrl': pageLocation,
        page_path: pagePath,
        page_title: pageTitle,
        page_location: pageLocation,
      })
      window.dataLayer.push({
        event: 'page_view',
        page_path: pagePath,
        page_title: pageTitle,
        page_location: pageLocation,
      })
      previousUrl.current = pageLocation
    }

    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(push)
    } else {
      setTimeout(push, 0)
    }
  }, [pathname, search])

  if (!GTM_ID) {
    return null
  }

  return (
    <>
      <Script id="gtm-base" strategy="afterInteractive">
        {`
          (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
          new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
          j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
          'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
          })(window,document,'script','dataLayer','${GTM_ID}');
        `}
      </Script>
      <noscript>
        <iframe
          src={`https://www.googletagmanager.com/ns.html?id=${GTM_ID}`}
          height="0"
          width="0"
          style={{ display: 'none', visibility: 'hidden' }}
        />
      </noscript>
    </>
  )
}
