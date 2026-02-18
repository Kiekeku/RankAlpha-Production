import { api } from '@/lib/api'

export async function fetchSparklinePriceMap(symbols: string[], limit = 40): Promise<Record<string, number[]>> {
  const entries = await Promise.all(
    symbols.map(async (symbol) => {
      try {
        const res = await api.getPriceHistory({ symbol, limit })
        const values = (res.items || [])
          .slice()
          .sort((a, b) => (a.price_date || '').localeCompare(b.price_date || ''))
          .map((p) => (typeof p.adj_close_px === 'number' ? p.adj_close_px : p.close_px))
          .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
        return [symbol, values] as const
      } catch {
        return [symbol, []] as const
      }
    }),
  )
  return Object.fromEntries(entries) as Record<string, number[]>
}
