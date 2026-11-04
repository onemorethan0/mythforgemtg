import { describe, it, expect } from 'vitest'
import { normalizeManaCost, colorsFromCost } from './manaCost'

describe('normalizeManaCost', () => {
  it('braces a cost typed without them', () => {
    expect(normalizeManaCost('2WU')).toBe('{2}{W}{U}')
    expect(normalizeManaCost('XRR')).toBe('{X}{R}{R}')
    expect(normalizeManaCost('10')).toBe('{10}')
  })

  it('upper-cases and ignores spaces and slashes', () => {
    expect(normalizeManaCost('2 w u')).toBe('{2}{W}{U}')
    expect(normalizeManaCost('w/u')).toBe('{W}{U}')
  })

  it('leaves a braced, empty or unparseable cost exactly as typed', () => {
    expect(normalizeManaCost('{2}{W}')).toBe('{2}{W}')
    expect(normalizeManaCost('')).toBe('')
    expect(normalizeManaCost(null)).toBe('')
    expect(normalizeManaCost(undefined)).toBe('')
    expect(normalizeManaCost('hello')).toBe('hello')
    expect(normalizeManaCost('2WQ')).toBe('2WQ')
  })

  it('trims surrounding whitespace', () => {
    expect(normalizeManaCost('  2W  ')).toBe('{2}{W}')
    expect(normalizeManaCost('   ')).toBe('')
  })

  it('is idempotent', () => {
    for (const raw of ['2WU', '{1}{G}', 'XX', 'hello', '']) {
      const once = normalizeManaCost(raw)
      expect(normalizeManaCost(once)).toBe(once)
    }
  })
})

describe('colorsFromCost', () => {
  it('returns colours in WUBRG order, de-duplicated', () => {
    expect(colorsFromCost('{R}{B}{U}{R}')).toEqual(['U', 'B', 'R'])
    expect(colorsFromCost('GWG')).toEqual(['W', 'G'])
  })

  it('reads hybrid and phyrexian symbols', () => {
    expect(colorsFromCost('{W/U}')).toEqual(['W', 'U'])
    expect(colorsFromCost('{2/W}')).toEqual(['W'])
    expect(colorsFromCost('{G/P}')).toEqual(['G'])
  })

  it('has no colour for generic, colourless, X or empty costs', () => {
    expect(colorsFromCost('{3}')).toEqual([])
    expect(colorsFromCost('{C}{C}')).toEqual([])
    expect(colorsFromCost('{X}')).toEqual([])
    expect(colorsFromCost('')).toEqual([])
    expect(colorsFromCost(undefined)).toEqual([])
  })
})
