'use client'

import { useCallback } from 'react'

import { useToast } from '@/components/ui/use-toast'

export function useShareCurrentView({
  successTitle = 'Link copied',
  successDescription = 'Shareable URL copied to clipboard.',
  failureTitle = 'Copy failed',
  failureDescription = 'Clipboard access was blocked.',
}: {
  successTitle?: string
  successDescription?: string
  failureTitle?: string
  failureDescription?: string
} = {}) {
  const { toast } = useToast()

  return useCallback(async () => {
    if (typeof window === 'undefined') return
    try {
      await navigator.clipboard.writeText(window.location.href)
      toast({ title: successTitle, description: successDescription })
    } catch {
      toast({ title: failureTitle, description: failureDescription })
    }
  }, [failureDescription, failureTitle, successDescription, successTitle, toast])
}
