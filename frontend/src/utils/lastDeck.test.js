import { describe, it, expect } from 'vitest'
import { rememberLastDeck, readLastDeck, forgetLastDeck, timeAgo } from './lastDeck'

const ID = '0123456789abcdef'
const memStore = () => {
  const m = new Map()
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v), removeItem: k => m.delete(k) }
}
const brokenStore = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') }, removeItem() { throw new Error('blocked') } }

describe('remember / read / forget', () => {
  it('round-trips a deck', () => {
    const s = memStore()
    rememberLastDeck(s, ID, 'Locutus of Borg', 1000)
    expect(readLastDeck(s)).toEqual({ id: ID, name: 'Locutus of Borg', at: 1000 })
    forgetLastDeck(s)
    expect(readLastDeck(s)).toBeNull()
  })
  it('refuses to remember a malformed id or an empty name', () => {
    const s = memStore()
    rememberLastDeck(s, 'zzz', 'X'); rememberLastDeck(s, ID, '')
    expect(readLastDeck(s)).toBeNull()
  })
  it('reads junk as nothing, never a route-unsafe id', () => {
    const s = memStore()
    s.setItem('mtg_last_deck', '{not json'); expect(readLastDeck(s)).toBeNull()
    s.setItem('mtg_last_deck', JSON.stringify({ id: '../etc', name: 'x', at: 1 })); expect(readLastDeck(s)).toBeNull()
    s.setItem('mtg_last_deck', JSON.stringify({ id: ID, at: 1 })); expect(readLastDeck(s)).toBeNull()
  })
  it('survives storage being blocked', () => {
    expect(() => rememberLastDeck(brokenStore, ID, 'x')).not.toThrow()
    expect(readLastDeck(brokenStore)).toBeNull()
    expect(() => forgetLastDeck(brokenStore)).not.toThrow()
  })
})

describe('timeAgo', () => {
  const now = 1_000_000_000
  it('writes the unit that reads naturally', () => {
    expect(timeAgo(now - 10_000, now)).toBe('just now')
    expect(timeAgo(now - 90_000, now)).toBe('2 minutes ago')
    expect(timeAgo(now - 60 * 60_000, now)).toBe('an hour ago')
    expect(timeAgo(now - 5 * 3_600_000, now)).toBe('5 hours ago')
    expect(timeAgo(now - 24 * 3_600_000, now)).toBe('yesterday')
    expect(timeAgo(now - 3 * 86_400_000, now)).toBe('3 days ago')
    expect(timeAgo(now - 21 * 86_400_000, now)).toBe('3 weeks ago')
  })
  it('never says a future or unknown time', () => {
    expect(timeAgo(now + 5000, now)).toBe('just now')
    expect(timeAgo(0, now)).toBe('just now')
  })
})
