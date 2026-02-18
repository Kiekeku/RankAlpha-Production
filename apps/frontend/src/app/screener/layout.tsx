import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Screener',
  description: 'Pre-built screens for swing trading. Updated nightly.',
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}

