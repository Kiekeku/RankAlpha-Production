'use client'

import './globals.css'
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeftIcon, CopyIcon, RefreshCcwIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PrimaryCtaButton } from '@/components/primary-cta'

type ErrorProps = {
  error: Error & { digest?: string }
  reset: () => void
}

export default function GlobalError({ error, reset }: ErrorProps) {
  const router = useRouter()
  const [copied, setCopied] = useState(false)

  const errorId = useMemo(() => error?.digest || 'unknown', [error])
  const copyValue = errorId !== 'unknown' ? errorId : error?.message || 'unknown'

  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('[app:global-error]', error)
  }, [error])

  const handleBack = () => {
    try {
      if (window.history.length > 1) {
        router.back()
        return
      }
    } catch {
      // ignore
    }
    router.push('/overview/nowcast')
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(copyValue)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <html lang="en">
      <body className="bg-background text-foreground">
        <div className="min-h-screen px-4 py-10">
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
            <div className="rounded-3xl bg-gradient-to-br from-primary/8 via-card to-card px-4 py-6 shadow-md">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h1 className="text-2xl font-semibold tracking-tight">Something went wrong loading this view</h1>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Your data is safe. This is a temporary issue.
                  </p>
                </div>
                <PrimaryCtaButton onClick={reset}>
                  <RefreshCcwIcon className="h-4 w-4" aria-hidden />
                  Retry
                </PrimaryCtaButton>
              </div>
            </div>

            <Card className="border-destructive/20 bg-destructive/5">
              <CardContent className="space-y-4 pt-6">
                <div className="text-sm text-muted-foreground">
                  Error ID: <span className="font-mono text-xs">{errorId}</span>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-9 rounded-full px-4"
                    onClick={handleBack}
                  >
                    <ArrowLeftIcon className="mr-1 h-4 w-4" aria-hidden />
                    Back
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-9 rounded-full px-4"
                    onClick={handleCopy}
                  >
                    <CopyIcon className="mr-1 h-4 w-4" aria-hidden />
                    {copied ? 'Copied' : 'Copy error code'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </body>
    </html>
  )
}
