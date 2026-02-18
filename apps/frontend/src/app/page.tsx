'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'

export default function HomePage() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/overview/nowcast')
  }, [router])

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <div className="text-lg font-semibold">Redirecting to Overview…</div>
      <Link href="/overview/nowcast" className="text-sm font-semibold text-primary hover:underline">
        Open Overview
      </Link>
    </div>
  )
}
