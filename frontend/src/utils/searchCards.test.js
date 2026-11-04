import { describe, it, expect } from 'vitest'
import { searchCards } from './searchCards'

const cards = [
  { original_name: 'Sol Ring', themed_name: 'Sun Band', type_line: 'Artifact', oracle_text: '{T}: Add {C}{C}.', flavor_text: 'Bright.' },
  { original_name: 'Llanowar Elves', themed_name: 'Forest Scout', type_line: 'Creature — Elf Druid', oracle_text: '{T}: Add {G}.' },
  { original_name: 'Island', themed_name: 'Tide Flat', type_line: 'Basic Land — Island' },
]

describe('searchCards', () => {
  it('returns the original array for a blank or missing query', () => {
    expect(searchCards(cards, '')).toBe(cards)
    expect(searchCards(cards, '   ')).toBe(cards)
    expect(searchCards(cards, undefined)).toBe(cards)
    expect(searchCards(cards, null)).toBe(cards)
  })

  it('returns [] for a non-array input', () => {
    expect(searchCards(null, 'x')).toEqual([])
    expect(searchCards(undefined, 'x')).toEqual([])
    expect(searchCards('cards', 'x')).toEqual([])
  })

  it('matches case-insensitively on the original and the themed name', () => {
    expect(searchCards(cards, 'SOL').map(c => c.original_name)).toEqual(['Sol Ring'])
    expect(searchCards(cards, 'sun band').map(c => c.original_name)).toEqual(['Sol Ring'])
    expect(searchCards(cards, 'forest scout').map(c => c.original_name)).toEqual(['Llanowar Elves'])
  })

  it('searches type line, rules text and flavour text', () => {
    expect(searchCards(cards, 'druid').map(c => c.original_name)).toEqual(['Llanowar Elves'])
    expect(searchCards(cards, 'add {c}').map(c => c.original_name)).toEqual(['Sol Ring'])
    expect(searchCards(cards, 'bright').map(c => c.original_name)).toEqual(['Sol Ring'])
  })

  it('requires EVERY term to match, in any order, across fields', () => {
    expect(searchCards(cards, 'elf add').map(c => c.original_name)).toEqual(['Llanowar Elves'])
    expect(searchCards(cards, 'add elf')).toHaveLength(1)
    expect(searchCards(cards, 'elf artifact')).toEqual([])
  })

  it('keeps input order and tolerates extra spaces between terms', () => {
    expect(searchCards(cards, '  add    t  ').map(c => c.original_name)).toEqual(['Sol Ring', 'Llanowar Elves'])
  })

  it('does not match across the field boundary as one string', () => {
    // 'Sol Ring' + newline + 'Sun Band' must not let "ringsun" match
    expect(searchCards(cards, 'ringsun')).toEqual([])
  })

  it('ignores fields that are not strings', () => {
    const odd = [{ original_name: 'X', themed_name: null, type_line: 42, oracle_text: undefined }]
    expect(searchCards(odd, 'x')).toHaveLength(1)
    expect(searchCards(odd, '42')).toEqual([])
  })
})
