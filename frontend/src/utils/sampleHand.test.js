import { describe, expect, it } from 'vitest'
import {
  buildLibrary, drawHand, hypergeometricAtLeast, isLand, mulberry32, openingHandOdds, shuffle,
} from './sampleHand'

const land = (n, q = 1) => ({ original_name: n, type_line: 'Basic Land — Forest', quantity: q })
const spell = n => ({ original_name: n, type_line: 'Instant' })

describe('mulberry32', () => {
  it('is deterministic and spread over [0, 1)', () => {
    const a = mulberry32(42), b = mulberry32(42)
    const xs = Array.from({ length: 1000 }, () => a())
    expect(xs.slice(0, 5)).toEqual(Array.from({ length: 5 }, () => b()))
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(0)
    expect(Math.max(...xs)).toBeLessThan(1)
    const mean = xs.reduce((s, x) => s + x, 0) / xs.length
    expect(mean).toBeGreaterThan(0.45)          // the draft returned ~0 every call
    expect(mean).toBeLessThan(0.55)
  })
})

describe('buildLibrary', () => {
  it('expands quantities and drops the command zone case-insensitively', () => {
    const lib = buildLibrary([land('Forest', 3), spell('Thrasios, Triton Hero'), spell('Sol Ring')],
      ['THRASIOS, Triton Hero'])
    expect(lib.map(c => c.original_name)).toEqual(['Forest', 'Forest', 'Forest', 'Sol Ring'])
  })
  it('treats a missing or bad quantity as one', () => {
    expect(buildLibrary([{ original_name: 'A', quantity: 0 }, { original_name: 'B', quantity: 'x' }]))
      .toHaveLength(2)
  })
})

describe('shuffle / drawHand', () => {
  it('keeps every card and does not mutate', () => {
    const lib = buildLibrary([land('Forest', 10), spell('A'), spell('B')])
    const before = [...lib]
    const { hand, rest } = drawHand(lib, 7, mulberry32(1))
    expect(lib).toEqual(before)
    expect(hand).toHaveLength(7)
    expect(hand.length + rest.length).toBe(12)
    expect(shuffle(lib, mulberry32(3))).toHaveLength(12)
  })
})

describe('isLand', () => {
  it('matches deck_quality.is_land: any face, whole word', () => {
    expect(isLand({ type_line: 'Basic Land — Island' })).toBe(true)
    expect(isLand({ type_line: 'Instant // Land' })).toBe(true)        // MDFC can be the land drop
    expect(isLand({ type_line: 'Creature — Highlander' })).toBe(false)
  })
})

describe('hypergeometric', () => {
  it('matches a hand-computed value', () => {
    // 99 cards, 37 lands, 7 drawn: P(>=2 lands) = 0.81418 (exact, Python math.comb)
    expect(hypergeometricAtLeast(99, 37, 7, 2)).toBeCloseTo(0.81418, 4)
    expect(hypergeometricAtLeast(10, 0, 7, 1)).toBe(0)
    expect(hypergeometricAtLeast(10, 10, 7, 7)).toBeCloseTo(1, 10)
    expect(hypergeometricAtLeast(5, 3, 0, 0)).toBe(1)
  })
  it('opening-hand odds sum consistently', () => {
    const lib = buildLibrary([land('Forest', 37), ...Array.from({ length: 62 }, (_, i) => spell(`S${i}`))])
    const o = openingHandOdds(lib)
    expect(o.lands).toBe(37)
    expect(o.total).toBe(99)
    expect(o.p2to4Lands).toBeLessThanOrEqual(o.pAtLeast2Lands)
    expect(o.pAtLeast3Lands).toBeLessThan(o.pAtLeast2Lands)
  })
})
