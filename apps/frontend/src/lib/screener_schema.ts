export type ScreenerSeoItem = {
  symbol: string
  company_name?: string
  consensus_score?: number
}

export function buildScreenerLeadersItemListJson({
  name,
  siteUrl,
  items,
}: {
  name: string
  siteUrl: string
  items: ScreenerSeoItem[]
}): string | null {
  if (!items.length) return null
  return JSON.stringify(
    {
      '@context': 'https://schema.org',
      '@type': 'ItemList',
      name,
      itemListOrder: 'https://schema.org/ItemListOrderDescending',
      itemListElement: items
        .filter((item) => item?.symbol)
        .map((item, index) => ({
          '@type': 'ListItem',
          position: index + 1,
          item: {
            '@type': 'Corporation',
            name: item.company_name || item.symbol,
            tickerSymbol: item.symbol,
            url: `${siteUrl}/ticker/${encodeURIComponent(item.symbol)}`,
            description:
              item.consensus_score != null
                ? `Consensus score ${Math.round(Number(item.consensus_score))}`
                : undefined,
          },
        })),
    },
    null,
    0,
  ).replace(/</g, '\\u003c')
}
