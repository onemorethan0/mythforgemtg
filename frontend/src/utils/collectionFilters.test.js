import { describe, it, expect } from 'vitest'
import { EMPTY_FILTERS, hasFilters, filterQuery } from './collectionFilters'

describe('collection filters', () => {
  it('empty filters are inactive and produce an empty query', () => {
    expect(hasFilters(EMPTY_FILTERS)).toBe(false)
    expect(filterQuery(EMPTY_FILTERS).toString()).toBe('')
  })

  it('serializes the printing filters as comma lists and a boolean', () => {
    const f = { ...EMPTY_FILTERS, finishes: ['foil', 'etched'], treatments: ['borderless'],
                languages: ['ja'], multi_printing: true }
    const p = filterQuery(f)
    expect(p.get('finishes')).toBe('foil,etched')
    expect(p.get('treatments')).toBe('borderless')
    expect(p.get('languages')).toBe('ja')
    expect(p.get('multi_printing')).toBe('true')
    expect(hasFilters(f)).toBe(true)
  })

  it.each(['finishes', 'treatments', 'languages'])('%s alone activates the filter', k => {
    expect(hasFilters({ ...EMPTY_FILTERS, [k]: ['x'] })).toBe(true)
  })

  it('multi_printing alone activates the filter and is omitted when off', () => {
    expect(hasFilters({ ...EMPTY_FILTERS, multi_printing: true })).toBe(true)
    expect(filterQuery({ ...EMPTY_FILTERS, multi_printing: false }).has('multi_printing')).toBe(false)
  })

  it('keeps the numeric and Game Changer filters, including 0', () => {
    const p = filterQuery({ ...EMPTY_FILTERS, cmc_min: 0, cmc_max: 3, min_count: 2,
                            game_changers_only: true })
    expect(p.get('cmc_min')).toBe('0')
    expect(p.get('cmc_max')).toBe('3')
    expect(p.get('min_count')).toBe('2')
    expect(p.get('game_changers_only')).toBe('true')
  })

  it('tolerates a partial state object', () => {
    expect(hasFilters({ colors: ['W'] })).toBe(true)
    expect(filterQuery({ colors: ['W'] }).get('colors')).toBe('W')
    expect(hasFilters({})).toBe(false)
  })
})
