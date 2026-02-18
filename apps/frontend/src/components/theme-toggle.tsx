"use client"

import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'

type ThemeToggleVariant = 'default' | 'menu'

export function ThemeToggle({ variant = 'default' }: { variant?: ThemeToggleVariant }) {
  const [dark, setDark] = useState<boolean>(true)

  useEffect(() => {
    try {
      const stored = localStorage.getItem('theme')
      if (stored) setDark(stored === 'dark')
      else setDark(true)
    } catch {}
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (dark) root.classList.add('dark')
    else root.classList.remove('dark')
    try {
      localStorage.setItem('theme', dark ? 'dark' : 'light')
    } catch {}
  }, [dark])

  const baseClasses =
    variant === 'menu'
      ? 'inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent'
      : 'inline-flex h-8 w-8 items-center justify-center rounded-md border hover:bg-accent'

  return (
    <button
      aria-label="Toggle theme"
      onClick={() => setDark((d) => !d)}
      className={baseClasses}
    >
      {variant === 'menu' ? (
        <>
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          <span>{dark ? 'Light' : 'Dark'}</span>
        </>
      ) : dark ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </button>
  )
}
