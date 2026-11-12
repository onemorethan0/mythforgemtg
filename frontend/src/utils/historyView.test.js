import { describe, it, expect } from 'vitest'
import { matchesQuery, sortEntries, selectableIds } from './historyView'

const D = (over) => ({ job_id: 'a'.repeat(16), status: null, ...over })
const DECKS = [
  D({ job_id: '1'.repeat(16), commander_name: 'Locutus of Borg', themed_name: 'Locutus of Borg', theme: 'Star Trek', built_at: 300, measured_bracket: 2, measured_label: 'Core' }),
  D({ job_id: '2'.repeat(16), commander_name: "Y'shtola, Night's Blessed", theme: 'Final Fantasy', built_at: 500, bracket: 3, bracket_label: 'Upgraded' }),
  D({ job_id: '3'.repeat(16), commander_name: 'Atraxa', built_at: 100 }),
  D({ job_id: '4'.repeat(16), commander_name: 'Zur the Enchanter', built_at: 400, status: 'building', bracket: 4 }),
]

describe('matchesQuery', () => {
  it('matches everything for an empty or blank query', () => {
    for (const q of ['', '   ', null, undefined]) expect(DECKS.every(d => matchesQuery(d, q))).toBe(true)
  })
  it('matches names and themes case-insensitively', () => {
    expect(matchesQuery(DECKS[0], 'locutus')).toBe(true)
    expect(matchesQuery(DECKS[0], 'STAR trek')).toBe(true)
    expect(matchesQuery(DECKS[0], 'atraxa')).toBe(false)
  })
  it('needs every word, in any order', () => {
    expect(matchesQuery(DECKS[0], 'borg trek')).toBe(true)
    expect(matchesQuery(DECKS[0], 'borg wizard')).toBe(false)
  })
  it('matches a bracket by number or label, measured first', () => {
    expect(matchesQuery(DECKS[0], 'b2')).toBe(true)
    expect(matchesQuery(DECKS[0], 'bracket 2')).toBe(true)
    expect(matchesQuery(DECKS[0], 'core')).toBe(true)
    expect(matchesQuery(DECKS[1], 'upgraded')).toBe(true)
    expect(matchesQuery(DECKS[1], 'b2')).toBe(false)
  })
  it('does not throw on a sparse entry', () => {
    expect(matchesQuery({}, 'x')).toBe(false)
    expect(matchesQuery({}, '')).toBe(true)
  })
})

describe('sortEntries', () => {
  const ids = list => list.map(d => d.job_id[0])
  it('recent puts the newest first', () => expect(ids(sortEntries(DECKS, 'recent'))).toEqual(['2', '4', '1', '3']))
  it('name sorts A to Z ignoring case', () => expect(ids(sortEntries(DECKS, 'name'))).toEqual(['3', '1', '2', '4']))
  it('bracket puts the highest first, newest within a bracket, and unmeasured last', () =>
    expect(ids(sortEntries(DECKS, 'bracket'))).toEqual(['4', '2', '1', '3']))
  it('an unknown mode falls back to recent', () => expect(ids(sortEntries(DECKS, 'nope'))).toEqual(['2', '4', '1', '3']))
  it('does not change the list it was given', () => {
    const copy = [...DECKS]
    sortEntries(DECKS, 'name')
    expect(DECKS).toEqual(copy)
  })
})

describe('selectableIds', () => {
  it('skips a deck that is still building', () =>
    expect(selectableIds(DECKS, '')).toEqual(['1'.repeat(16), '2'.repeat(16), '3'.repeat(16)]))
  it('is limited to what the search shows, so a bulk action cannot reach a hidden deck', () => {
    expect(selectableIds(DECKS, 'locutus')).toEqual(['1'.repeat(16)])
    expect(selectableIds(DECKS, 'nothing matches')).toEqual([])
  })
})
