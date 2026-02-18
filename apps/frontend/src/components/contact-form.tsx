'use client'

import { useEffect, useState } from 'react'
import Script from 'next/script'

type Status = 'idle' | 'submitting' | 'success' | 'error'

export function ContactForm() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [website, setWebsite] = useState('') // honeypot
  const [token, setToken] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)

  // Expose a global callback for Turnstile to call on success
  useEffect(() => {
    ;(window as any).onTurnstileSuccess = (t: string) => setToken(t)
    return () => { delete (window as any).onTurnstileSuccess }
  }, [])

  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || ''

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setStatus('submitting')
    setError(null)
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, message, website, token }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.error || `Failed with ${res.status}`)
      }
      setStatus('success')
      setName(''); setEmail(''); setMessage(''); setWebsite(''); setToken('')
    } catch (err: any) {
      setError(String(err?.message || err))
      setStatus('error')
    }
  }

  return (
    <div className="mt-4">
      <Script src="https://challenges.cloudflare.com/turnstile/v0/api.js" defer />
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-muted-foreground">Name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              required
              className="mt-1 h-9 w-full rounded-md border px-3 text-sm bg-background text-foreground"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground">Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              className="mt-1 h-9 w-full rounded-md border px-3 text-sm bg-background text-foreground"
            />
          </div>
        </div>
        <div className="hidden">
          <label>Website</label>
          <input type="text" value={website} onChange={e => setWebsite(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground">Message</label>
          <textarea
            value={message}
            onChange={e => setMessage(e.target.value)}
            required
            rows={5}
            className="mt-1 w-full rounded-md border px-3 py-2 text-sm bg-background text-foreground"
          />
        </div>
        <div className="cf-turnstile" data-sitekey={siteKey} data-callback="onTurnstileSuccess" />
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={status === 'submitting'}
            className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {status === 'submitting' ? 'Sending…' : 'Send message'}
          </button>
          {status === 'success' && <span className="text-xs text-status-success">Thanks - we’ll get back to you soon.</span>}
          {status === 'error' && <span className="text-xs text-status-danger">{error || 'Something went wrong.'}</span>}
        </div>
      </form>
    </div>
  )
}
