'use client'

import * as React from 'react'

type GlossaryContextValue = {
  isOpen: boolean
  term: string | null
  open: (term?: string | null) => void
  close: () => void
}

const GlossaryContext = React.createContext<GlossaryContextValue | null>(null)

export function GlossaryProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = React.useState(false)
  const [term, setTerm] = React.useState<string | null>(null)

  const open = (nextTerm?: string | null) => {
    if (nextTerm !== undefined) setTerm(nextTerm)
    setIsOpen(true)
  }

  const close = () => setIsOpen(false)

  const value: GlossaryContextValue = {
    isOpen,
    term,
    open,
    close,
  }

  return <GlossaryContext.Provider value={value}>{children}</GlossaryContext.Provider>
}

export function useGlossary() {
  const ctx = React.useContext(GlossaryContext)
  if (!ctx) throw new Error('useGlossary must be used within GlossaryProvider')
  return ctx
}

