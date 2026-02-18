"use client"

import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { OptionCount } from '@/lib/api'

type MultiSelectProps = {
  label: string
  options: OptionCount[] | undefined
  value: string[]
  onChange: (next: string[]) => void
  placeholder?: string
  className?: string
  labelClassName?: string
  hideLabel?: boolean
}

export function MultiSelect({
  label,
  options,
  value,
  onChange,
  placeholder = 'Search…',
  className,
  labelClassName,
  hideLabel = false,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({})

  // Close on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      const t = e.target as Node
      if (buttonRef.current && buttonRef.current.contains(t)) return
      if (menuRef.current && menuRef.current.contains(t)) return
      if (ref.current && ref.current.contains(t)) return
      setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [open])

  // Position the menu via fixed portal; recompute on open/resize/scroll
  useEffect(() => {
    function compute() {
      const el = buttonRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      setMenuStyle({
        position: 'fixed',
        top: r.bottom + 4,
        left: Math.max(8, Math.min(r.left, window.innerWidth - 320)),
        width: Math.min(Math.max(r.width, 280), 480),
        zIndex: 1000,
      })
    }
    if (open) {
      compute()
      const onScroll = () => compute()
      const onResize = () => compute()
      window.addEventListener('scroll', onScroll, true)
      window.addEventListener('resize', onResize)
      return () => {
        window.removeEventListener('scroll', onScroll, true)
        window.removeEventListener('resize', onResize)
      }
    }
  }, [open])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = options || []
    if (!q) return list
    return list.filter(o => o.name.toLowerCase().includes(q))
  }, [options, query])

  const showCounts = useMemo(() => {
    const list = options || []
    return list.some((o) => typeof o.count === 'number' && o.count > 0)
  }, [options])

  function toggle(item: string) {
    const set = new Set(value)
    if (set.has(item)) set.delete(item)
    else set.add(item)
    onChange(Array.from(set))
  }

  function selectAllCurrent() {
    const names = filtered.map(o => o.name)
    const merged = Array.from(new Set([...value, ...names]))
    onChange(merged)
  }

  function clearAll() { onChange([]) }

  return (
    <div className={`relative ${className || ''}`} ref={ref}>
      {!hideLabel ? (
        <div className="flex items-center justify-between">
          <label className={labelClassName || 'text-sm font-medium'}>{label}</label>
          {value.length > 0 && (
            <button type="button" className="text-xs text-muted-foreground hover:underline" onClick={clearAll}>Clear all</button>
          )}
        </div>
      ) : null}
      <button
        type="button"
        ref={buttonRef}
        onClick={() => setOpen(v => !v)}
        className="mt-1 w-full justify-between rounded-md border px-3 py-2 text-sm hover:bg-accent flex items-center gap-2"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <div className="flex flex-wrap items-center gap-2">
          {value.length === 0 ? (
            <span className="text-muted-foreground">Select {label.toLowerCase()}</span>
          ) : (
            <>
              <span className="font-semibold text-foreground">{label} ({value.length})</span>
              <span className="text-xs text-muted-foreground">{value.slice(0, 2).join(', ')}{value.length > 2 ? '…' : ''}</span>
            </>
          )}
        </div>
        <span className="text-xs text-muted-foreground">{open ? '▲' : '▼'}</span>
      </button>
      {open && createPortal(
        <div ref={menuRef} style={menuStyle} className="rounded-md border bg-popover text-popover-foreground shadow-md" onMouseDown={(e) => e.stopPropagation()}>
          <div className="p-2">
            <input
              className="w-full rounded-md border px-2 py-1 text-sm"
              placeholder={placeholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="flex items-center justify-between px-2 pb-2 gap-2 text-xs">
            <div className="flex items-center gap-2">
              <button type="button" className="rounded-md border px-2 py-1 hover:bg-accent" onClick={selectAllCurrent}>Select all</button>
              <button type="button" className="rounded-md border px-2 py-1 hover:bg-accent" onClick={clearAll}>Clear</button>
            </div>
            <div className="text-muted-foreground">{filtered.length} options</div>
          </div>
          <div role="listbox" className="max-h-64 overflow-auto p-1">
            {filtered.map((opt) => {
              const checked = value.includes(opt.name)
              return (
                <label key={opt.name} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-accent">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={checked}
                    onChange={() => toggle(opt.name)}
                  />
                  <span className="flex-1 truncate">{opt.name}</span>
                  {showCounts ? (
                    <span className="text-xs text-muted-foreground">{opt.count}</span>
                  ) : null}
                </label>
              )
            })}
            {filtered.length === 0 && (
              <div className="px-3 py-6 text-center text-sm text-muted-foreground">No matches</div>
            )}
          </div>
          <div className="border-t p-2">
            <div className="flex flex-wrap gap-1">
              {value.map(v => (
                <button key={v} type="button" onClick={() => toggle(v)} className="rounded-md border px-2 py-0.5 text-xs hover:bg-accent">
                  {v} ✕
                </button>
              ))}
            </div>
          </div>
        </div>, document.body)
      }
    </div>
  )
}
