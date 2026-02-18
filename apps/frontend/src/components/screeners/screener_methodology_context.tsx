'use client'

import * as React from 'react'

type ScreenerMethodologyContextValue = {
  isOpen: boolean
  open: () => void
  close: () => void
}

const ScreenerMethodologyContext = React.createContext<ScreenerMethodologyContextValue | null>(null)

export function ScreenerMethodologyProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = React.useState(false)
  const open = () => setIsOpen(true)
  const close = () => setIsOpen(false)
  return <ScreenerMethodologyContext.Provider value={{ isOpen, open, close }}>{children}</ScreenerMethodologyContext.Provider>
}

export function useScreenerMethodology() {
  const ctx = React.useContext(ScreenerMethodologyContext)
  if (!ctx) throw new Error('useScreenerMethodology must be used within ScreenerMethodologyProvider')
  return ctx
}

