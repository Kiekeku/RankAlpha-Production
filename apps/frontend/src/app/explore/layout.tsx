import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Explore',
  description: 'Explore rankings, screeners, and market snapshots.',
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}

