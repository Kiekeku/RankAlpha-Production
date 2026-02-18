import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'AI Feed',
  description: 'Latest AI memos with catalysts, scenarios, risks, and peers.',
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
