import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Disclaimer',
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}

