import { describe, expect, it } from 'vitest'

import { cacheControlForPayload } from '@/app/api/_utils/upstream'

describe('cacheControlForPayload', () => {
  const cacheControl = 's-maxage=60, stale-while-revalidate=120'

  it('returns no-store for empty arrays', () => {
    expect(cacheControlForPayload([], cacheControl)).toBe('no-store, max-age=0')
  })

  it('returns no-store for empty objects', () => {
    expect(cacheControlForPayload({}, cacheControl)).toBe('no-store, max-age=0')
  })

  it('returns no-store for {status: \"empty\"} payloads (case/whitespace-insensitive)', () => {
    expect(cacheControlForPayload({ status: 'empty' }, cacheControl)).toBe('no-store, max-age=0')
    expect(cacheControlForPayload({ status: ' EMPTY ' }, cacheControl)).toBe('no-store, max-age=0')
    expect(cacheControlForPayload({ status: 'Empty', extra: 123 }, cacheControl)).toBe('no-store, max-age=0')
  })

  it('returns provided cacheControl for non-empty payloads', () => {
    expect(cacheControlForPayload(null, cacheControl)).toBe(cacheControl)
    expect(cacheControlForPayload([1], cacheControl)).toBe(cacheControl)
    expect(cacheControlForPayload({ status: 'ok' }, cacheControl)).toBe(cacheControl)
    expect(cacheControlForPayload({ any: 'value' }, cacheControl)).toBe(cacheControl)
  })
})

