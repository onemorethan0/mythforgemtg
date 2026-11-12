import { describe, it, expect } from 'vitest'
import { parseHash, formatRoute } from './router'

const ID = '0123456789abcdef'

describe('parseHash', () => {
  it('reads the landing hub from an empty or root hash', () => {
    for (const h of ['', '#', '#/', undefined, null]) {
      expect(parseHash(h)).toEqual({ name: 'home', id: null })
    }
  })
  it('reads history and collection', () => {
    expect(parseHash('#/history')).toEqual({ name: 'history', id: null })
    expect(parseHash('#/collection')).toEqual({ name: 'collection', id: null })
  })
  it('reads a deck id', () => {
    expect(parseHash(`#/deck/${ID}`)).toEqual({ name: 'deck', id: ID })
  })
  it('treats anything malformed as home, never throws', () => {
    for (const h of ['#/deck/zzz', '#/deck/', `#/deck/${ID}/extra`, '#/deck/0123456789ABCDEF',
                     '#/nonsense', '#/history/x', 'deck/0123456789abcdef', '#%E0%A4%A']) {
      expect(parseHash(h), h).toEqual({ name: 'home', id: null })
    }
  })
})

describe('formatRoute', () => {
  it('writes each route', () => {
    expect(formatRoute('home')).toBe('#/')
    expect(formatRoute('history')).toBe('#/history')
    expect(formatRoute('collection')).toBe('#/collection')
    expect(formatRoute('deck', ID)).toBe(`#/deck/${ID}`)
  })
  it('refuses a deck route without a valid id', () => {
    expect(() => formatRoute('deck')).toThrow()
    expect(() => formatRoute('deck', 'zzz')).toThrow()
  })
  it('round-trips', () => {
    for (const [n, id] of [['home'], ['history'], ['collection'], ['deck', ID]]) {
      expect(parseHash(formatRoute(n, id))).toEqual({ name: n, id: id || null })
    }
  })
})
