'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { Suspense, useState } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { SessionProvider } from 'next-auth/react'
import { ONE_MIN_MS } from '@/lib/time'
import { CompareProvider } from '@/components/compare/compare_context'
import { CompareTray } from '@/components/compare/compare_tray'
import { GlossaryProvider } from '@/components/glossary/glossary_context'
import { GlossaryDrawer } from '@/components/glossary/glossary_drawer'
import { MethodologyProvider } from '@/components/methodology/methodology_context'
import { MethodologyDrawer } from '@/components/methodology/methodology_drawer'
import { FactorsProvider } from '@/components/factors/factors_context'
import { FactorsDrawer } from '@/components/factors/factors_drawer'
import { ScreenerMethodologyProvider } from '@/components/screeners/screener_methodology_context'
import { ScreenerMethodologyDrawer } from '@/components/screeners/screener_methodology_drawer'
import { FocusReturnHandler } from '@/components/focus_return_handler'
import { RouteMemory } from '@/components/route_memory'
import { KeyboardShortcuts } from '@/components/keyboard-shortcuts'

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: ONE_MIN_MS,
            retry: (failureCount, error) => {
              if (failureCount >= 2) return false
              const message = String(error || '').toLowerCase()
              if (message.includes('timeout') || message.includes('timed out')) return true
              if (message.includes('network') || message.includes('fetch')) return true
              if (error instanceof TypeError) return true
              return false
            },
            retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 4000),
          },
        },
      })
  )

  return (
    <SessionProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200}>
          <MethodologyProvider>
            <GlossaryProvider>
              <FactorsProvider>
                <ScreenerMethodologyProvider>
                  <CompareProvider>
                    <Suspense fallback={null}>
                      <RouteMemory />
                    </Suspense>
                    <KeyboardShortcuts />
                    {children}
                    <FocusReturnHandler />
                    <CompareTray />
                    <MethodologyDrawer renderButton={false} />
                    <GlossaryDrawer renderButton={false} />
                    <FactorsDrawer />
                    <ScreenerMethodologyDrawer />
                  </CompareProvider>
                </ScreenerMethodologyProvider>
              </FactorsProvider>
            </GlossaryProvider>
          </MethodologyProvider>
          <ReactQueryDevtools initialIsOpen={false} />
        </TooltipProvider>
      </QueryClientProvider>
    </SessionProvider>
  )
}
