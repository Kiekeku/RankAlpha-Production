'use client'

import * as React from 'react'

type FactorsContextValue = {
  isOpen: boolean
  open: () => void
  close: () => void
}

const FactorsContext = React.createContext<FactorsContextValue | null>(null)

export function FactorsProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = React.useState(false)

  const open = () => setIsOpen(true)
  const close = () => setIsOpen(false)

  return <FactorsContext.Provider value={{ isOpen, open, close }}>{children}</FactorsContext.Provider>
}

export function useFactors() {
  const ctx = React.useContext(FactorsContext)
  if (!ctx) throw new Error('useFactors must be used within FactorsProvider')
  return ctx
}

