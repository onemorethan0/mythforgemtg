import { describe, it, expect } from 'vitest'
import {
  availableFinishes, priceFor, cheapestPrice, ownedTotal, releaseYear,
  isCurrentPrint, filterPrintings, sortPrintings,
} from './printings'

const A = { id: 'a', set: 'lea', set_name: 'Alpha', cn: '1', released_at: '1993-08-05',
            finishes: ['nonfoil'], prices: { nonfoil: 100, foil: null, etched: null },
            owned: [{ row_id: 'r1', finish: 'nonfoil', count: 2 }] }
const B = { id: 'b', set: 'c21', set_name: 'Commander 2021', cn: '263', released_at: '2021-04-23',
            finishes: ['nonfoil', 'foil', 'etched'],
            prices: { nonfoil: 1.5, foil: 4, etched: null }, owned: [] }
const C = { id: 'c', set: 'xyz', set_name: 'Mystery', cn: '9', owned: [] }

describe('availableFinishes', () => {
  it('lists known finishes in canonical order', () => {
    expect(availableFinishes({ finishes: ['etched', 'foil', 'nonfoil'] })).toEqual(['nonfoil', 'foil', 'etched'])
  })
  it('offers only nonfoil when finishes is missing or empty', () => {
    expect(availableFinishes(C)).toEqual(['nonfoil'])
    expect(availableFinishes({ finishes: [] })).toEqual(['nonfoil'])
    expect(availableFinishes(null)).toEqual(['nonfoil'])
  })
  it('does not offer etched for a print without it', () => {
    expect(availableFinishes({ finishes: ['nonfoil', 'foil'] })).not.toContain('etched')
  })
})

describe('priceFor', () => {
  it('returns the finish own price, null when absent, never another finish', () => {
    expect(priceFor(B, 'foil')).toBe(4)
    expect(priceFor(B, 'etched')).toBeNull()
    expect(priceFor(A, 'foil')).toBeNull()
  })
  it('uses legacy usd for nonfoil only when there is no price block', () => {
    expect(priceFor({ usd: 3 }, 'nonfoil')).toBe(3)
    expect(priceFor({ usd: 3 }, 'foil')).toBeNull()
    expect(priceFor({ usd: 3, prices: { nonfoil: null } }, 'nonfoil')).toBeNull()
  })
})

describe('misc', () => {
  it('cheapestPrice ignores unpriced finishes', () => {
    expect(cheapestPrice(B)).toBe(1.5)
    expect(cheapestPrice(C)).toBeNull()
  })
  it('ownedTotal sums counts', () => {
    expect(ownedTotal(A)).toBe(2)
    expect(ownedTotal(C)).toBe(0)
  })
  it('releaseYear', () => {
    expect(releaseYear(B)).toBe('2021')
    expect(releaseYear(C)).toBe('')
  })
  it('isCurrentPrint compares set + cn case-insensitively', () => {
    expect(isCurrentPrint(B, { set: 'C21', cn: '263' })).toBe(true)
    expect(isCurrentPrint(B, { set: 'c21', cn: '1' })).toBe(false)
    expect(isCurrentPrint(B, { set: '', cn: '' })).toBe(false)
  })
})

describe('filterPrintings', () => {
  it('matches set code or name', () => {
    expect(filterPrintings([A, B, C], 'comm', false)).toEqual([B])
    expect(filterPrintings([A, B, C], 'LEA', false)).toEqual([A])
  })
  it('owned only', () => {
    expect(filterPrintings([A, B, C], '', true)).toEqual([A])
  })
})

describe('sortPrintings', () => {
  it('newest / oldest put undated last', () => {
    expect(sortPrintings([A, C, B], 'newest').map(p => p.id)).toEqual(['b', 'a', 'c'])
    expect(sortPrintings([C, B, A], 'oldest').map(p => p.id)).toEqual(['a', 'b', 'c'])
  })
  it('cheapest puts unpriced last', () => {
    expect(sortPrintings([C, A, B], 'cheapest').map(p => p.id)).toEqual(['b', 'a', 'c'])
  })
  it('does not mutate', () => {
    const l = [A, B]
    sortPrintings(l, 'oldest')
    expect(l[0]).toBe(A)
  })
})
