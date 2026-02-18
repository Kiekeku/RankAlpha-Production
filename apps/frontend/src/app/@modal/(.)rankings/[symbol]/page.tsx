import { redirect } from 'next/navigation'

export default async function RankingsSymbolModal({
  params,
  searchParams,
}: {
  params: { symbol: string }
  searchParams?: { [key: string]: string | string[] | undefined }
}) {
  const rawTab = searchParams?.tab
  const tab = Array.isArray(rawTab) ? rawTab[0] : rawTab
  const symbol = (params.symbol || '').trim().toUpperCase()
  const base = symbol ? `/ticker/${encodeURIComponent(symbol)}` : '/ticker'
  if (tab) {
    const params = new URLSearchParams()
    params.set('tab', tab)
    redirect(`${base}?${params.toString()}`)
  }
  redirect(base)
}
