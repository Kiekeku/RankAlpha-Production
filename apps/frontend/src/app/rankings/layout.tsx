import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Rankings',
  description: 'Factor grades and setup hits across the tracked universe.',
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
