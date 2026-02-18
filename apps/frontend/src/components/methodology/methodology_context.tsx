'use client'

import * as React from 'react'

type MethodologyContextValue = {
  isOpen: boolean
  section: string | null
  open: (section?: string | null) => void
  close: () => void
}

const MethodologyContext = React.createContext<MethodologyContextValue | null>(null)

export function MethodologyProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = React.useState(false)
  const [section, setSection] = React.useState<string | null>(null)

  const open = (nextSection?: string | null) => {
    if (nextSection !== undefined) setSection(nextSection)
    setIsOpen(true)
  }

  const close = () => setIsOpen(false)

  const value: MethodologyContextValue = {
    isOpen,
    section,
    open,
    close,
  }

  return <MethodologyContext.Provider value={value}>{children}</MethodologyContext.Provider>
}

export function useMethodology() {
  const ctx = React.useContext(MethodologyContext)
  if (!ctx) throw new Error('useMethodology must be used within MethodologyProvider')
  return ctx
}

