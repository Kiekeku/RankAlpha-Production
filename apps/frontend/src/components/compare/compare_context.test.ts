import { describe, expect, it } from 'vitest'

import { buildComparePageUrl } from '@/components/compare/compare_context'

function qs(url: string): URLSearchParams {
  const u = new URL(url, 'https://example.com')
  return u.searchParams
}

describe('buildComparePageUrl', () => {
  it('normalizes, de-dupes, and caps tickers at 3', () => {
    const url = buildComparePageUrl({
      symbols: ['aa', 'AA', 'nvda', 'msft', 'goog'],
      baseline: 'AA',
      mode: 'table',
      deltas: true,
    })
    const params = qs(url)
    expect(params.get('symbols')).toBe('AA,NVDA,MSFT')
  })

  it('omits invalid symbols and invalid baseline', () => {
    const url = buildComparePageUrl({
      symbols: ['NVDA', '??', 'MSFT'],
      baseline: '???',
      mode: 'table',
      deltas: true,
    })
    const params = qs(url)
    expect(params.get('symbols')).toBe('NVDA,MSFT')
    expect(params.has('baseline')).toBe(false)
  })

  it('includes baseline only when it is selected', () => {
    const url = buildComparePageUrl({
      symbols: ['NVDA', 'MSFT'],
      baseline: 'MSFT',
      mode: 'table',
      deltas: true,
    })
    const params = qs(url)
    expect(params.get('baseline')).toBe('MSFT')
  })

  it('encodes mode and deltas', () => {
    const url = buildComparePageUrl({
      symbols: ['NVDA', 'MSFT'],
      baseline: 'NVDA',
      mode: 'cards',
      deltas: false,
    })
    const params = qs(url)
    expect(params.get('mode')).toBe('cards')
    expect(params.get('deltas')).toBe('0')
  })
})
