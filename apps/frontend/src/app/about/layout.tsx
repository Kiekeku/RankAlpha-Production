import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'About',
  description: 'Model explanation, current weights, and pipeline status.',
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}

