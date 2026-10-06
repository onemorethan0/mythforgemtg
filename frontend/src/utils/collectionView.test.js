// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  DEFAULT_VIEW, VIEW_MODES, GROUP_BYS, SORT_KEYS, LIST_COLUMNS, TILE_SIZES,
  loadViewSettings, saveViewSettings, viewQuery, decklistLine, dotColor,
  effectiveGroupBy, splitByGroup, groupValueLabel,
} from './collectionView'

const KEY = 'mtg_coll_view_v2'
const LEGACY = 'mtg_coll_view'

// Minimal Storage stand-in.
const store = (init = {}) => {
  const m = new Map(Object.entries(init))
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    _m: m,
  }
}

describe('loadViewSettings', () => {
  it('returns defaults for empty storage', () => {
    expect(loadViewSettings(store())).toEqual(DEFAULT_VIEW)
  })

  it('migrates legacy grid', () => {
    const s = loadViewSettings(store({ [LEGACY]: 'grid' }))
    expect(s.mode).toBe('grid')
    expect(s.sort).toBe(DEFAULT_VIEW.sort)
  })

  it('migrates legacy list and ignores unknown legacy values', () => {
    expect(loadViewSettings(store({ [LEGACY]: 'list' })).mode).toBe('list')
    expect(loadViewSettings(store({ [LEGACY]: 'wat' })).mode).toBe('list')
  })

  it('v2 wins over the legacy key', () => {
    const s = loadViewSettings(store({ [KEY]: JSON.stringify({ mode: 'tiles' }), [LEGACY]: 'grid' }))
    expect(s.mode).toBe('tiles')
  })

  it('bad JSON -> defaults', () => {
    expect(loadViewSettings(store({ [KEY]: '{not json' }))).toEqual(DEFAULT_VIEW)
  })

  it('non-object JSON -> defaults', () => {
    for (const raw of ['null', '[]', '"x"', '7', 'true'])
      expect(loadViewSettings(store({ [KEY]: raw }))).toEqual(DEFAULT_VIEW)
  })

  it('throwing storage -> defaults', () => {
    const boom = { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') } }
    expect(loadViewSettings(boom)).toEqual(DEFAULT_VIEW)
  })

  it('null/undefined storage -> defaults', () => {
    expect(loadViewSettings(null)).toEqual(DEFAULT_VIEW)
    expect(loadViewSettings(undefined)).toEqual(DEFAULT_VIEW)
  })

  it('invalid mode falls back but valid sort is kept', () => {
    const s = loadViewSettings(store({ [KEY]: JSON.stringify({ mode: 'bogus', sort: 'price', direction: 'desc' }) }))
    expect(s.mode).toBe(DEFAULT_VIEW.mode)
    expect(s.sort).toBe('price')
    expect(s.direction).toBe('desc')
  })

  it('wrong types per field fall back individually', () => {
    const s = loadViewSettings(store({ [KEY]: JSON.stringify({
      mode: 5, size: {}, groupBy: ['type'], sort: null, direction: 'sideways',
      then: 7, thenDirection: 1, columns: 'set', collapsed: [1],
    }) }))
    expect(s).toEqual(DEFAULT_VIEW)
  })

  it('unknown column dropped', () => {
    const s = loadViewSettings(store({ [KEY]: JSON.stringify({ columns: ['set', 'nope', 'price', 3] }) }))
    expect(s.columns).toEqual(['set', 'price'])
  })

  it('duplicate columns collapse', () => {
    const s = loadViewSettings(store({ [KEY]: JSON.stringify({ columns: ['set', 'set', 'cn'] }) }))
    expect(s.columns).toEqual(['set', 'cn'])
  })

  it('an explicitly empty column list is kept', () => {
    const s = loadViewSettings(store({ [KEY]: JSON.stringify({ columns: [] }) }))
    expect(s.columns).toEqual([])
  })

  it('then must be a known sort key, else null', () => {
    expect(loadViewSettings(store({ [KEY]: JSON.stringify({ then: 'cmc' }) })).then).toBe('cmc')
    expect(loadViewSettings(store({ [KEY]: JSON.stringify({ then: 'zzz' }) })).then).toBeNull()
  })

  it('collapsed keeps per-grouping string arrays and drops everything else', () => {
    const s = loadViewSettings(store({ [KEY]: JSON.stringify({ collapsed: {
      type: ['Creature', 'Creature', 3, 'Land'], color: 'W', rarity: [], set: { a: 1 },
      none: ['x'], bogus: ['y'], cmc: ['0'],
    } }) }))
    expect(s.collapsed).toEqual({ type: ['Creature', 'Land'], cmc: ['0'] })
  })

  it('the old flat collapsed shape and non-objects fall back to empty', () => {
    for (const bad of [{ a: true }, [1], 'x', 5, null]) {
      const s = loadViewSettings(store({ [KEY]: JSON.stringify({ collapsed: bad }) }))
      expect(s.collapsed).toEqual({})
    }
  })

  it('collapsed round-trips through save', () => {
    const st = store()
    const s = { ...DEFAULT_VIEW, groupBy: 'type', collapsed: { type: ['Creature'] } }
    saveViewSettings(st, s)
    expect(loadViewSettings(st)).toEqual(s)
  })

  it('never aliases the DEFAULT_VIEW arrays/objects', () => {
    const s = loadViewSettings(store())
    s.columns.push('x'); s.collapsed.type = ['z']
    expect(DEFAULT_VIEW.columns).toEqual(['set', 'finish', 'type', 'price'])
    expect(DEFAULT_VIEW.collapsed).toEqual({})
  })
})

describe('saveViewSettings', () => {
  it('round-trips', () => {
    const st = store()
    const s = { ...DEFAULT_VIEW, mode: 'grid', sort: 'value', then: 'name', columns: ['cn'] }
    saveViewSettings(st, s)
    expect(loadViewSettings(st)).toEqual(s)
  })

  it('does not throw when storage throws', () => {
    const boom = { setItem() { throw new Error('quota') } }
    expect(() => saveViewSettings(boom, DEFAULT_VIEW)).not.toThrow()
    expect(() => saveViewSettings(null, DEFAULT_VIEW)).not.toThrow()
  })
})

describe('viewQuery', () => {
  const asObj = s => Object.fromEntries(viewQuery(s))

  it('omits group none and null then', () => {
    const q = asObj(DEFAULT_VIEW)
    expect(q).toEqual({ sort: 'name', direction: 'asc' })
    expect('group' in q).toBe(false)
    expect('then' in q).toBe(false)
    expect('then_direction' in q).toBe(false)
  })

  it('includes group and then when set', () => {
    const q = asObj({ ...DEFAULT_VIEW, groupBy: 'type', then: 'cmc', thenDirection: 'desc', sort: 'price', direction: 'desc' })
    expect(q).toEqual({ sort: 'price', direction: 'desc', then: 'cmc', then_direction: 'desc', group: 'type' })
  })
})

describe('constants', () => {
  it('match the agreed shapes', () => {
    expect(VIEW_MODES).toEqual(['list', 'compact', 'grid', 'tiles', 'stacks'])
    expect(GROUP_BYS).toEqual(['none', 'type', 'color', 'cmc', 'rarity', 'set', 'finish', 'card'])
    expect(SORT_KEYS.map(([k]) => k)).toEqual([
      'name', 'value', 'price', 'count', 'cmc', 'type', 'set', 'edhrec',
      'rarity', 'color', 'released', 'collector', 'added', 'finish',
    ])
    expect(TILE_SIZES).toEqual({ s: 120, m: 160, l: 220 })
    expect(LIST_COLUMNS).toHaveLength(12)
  })
})

describe('decklistLine', () => {
  it('writes qty, name, set, collector number and finish marker', () => {
    expect(decklistLine({ count: 3, name: 'Sol Ring', set: 'c21', cn: '263', finish: 'foil' }))
      .toBe('3x Sol Ring (C21) 263 *F*')
    expect(decklistLine({ count: 1, name: 'Sol Ring', set: 'c21', cn: '263', finish: 'etched' }))
      .toBe('1x Sol Ring (C21) 263 *E*')
    expect(decklistLine({ count: 2, name: 'Sol Ring', set: 'c21', cn: '263', finish: 'nonfoil' }))
      .toBe('2x Sol Ring (C21) 263')
  })
  it('omits the set when unknown and the number when blank', () => {
    expect(decklistLine({ count: 4, name: 'Island', set: '', cn: '9', finish: 'nonfoil' }))
      .toBe('4x Island')
    expect(decklistLine({ count: 1, name: 'Island', finish: 'foil' })).toBe('1x Island *F*')
    expect(decklistLine({ count: 1, name: 'Fire // Ice', set: 'mh2', cn: '', finish: 'nonfoil' }))
      .toBe('1x Fire // Ice (MH2)')
  })
})

describe('dotColor', () => {
  it('is null for unresolved rows and Multicolor for gold ones', () => {
    expect(dotColor({ resolved: false, colors: ['R'] })).toBeNull()
    expect(dotColor({ resolved: true, colors: ['R', 'G'] })).toBe('#c9a227')
    expect(dotColor({ resolved: true, colors: [] })).toBe('#8a8a8a')
  })
})

describe('stacks grouping', () => {
  it('stacks with group none asks the server for type', () => {
    expect(effectiveGroupBy({ mode: 'stacks', groupBy: 'none' })).toBe('type')
    expect(Object.fromEntries(viewQuery({ ...DEFAULT_VIEW, mode: 'stacks' })).group).toBe('type')
  })

  it('an explicit grouping wins, and other modes are unchanged', () => {
    expect(effectiveGroupBy({ mode: 'stacks', groupBy: 'rarity' })).toBe('rarity')
    expect(effectiveGroupBy({ mode: 'list', groupBy: 'none' })).toBe('none')
    expect('group' in Object.fromEntries(viewQuery({ ...DEFAULT_VIEW, mode: 'grid' }))).toBe(false)
  })
})

describe('splitByGroup', () => {
  const groups = [
    { key: 'Creature', label: 'Creature', rows: 3, cards: 5, value: 1.5 },
    { key: 'Land', label: 'Land', rows: 2, cards: 6, value: 0 },
    { key: 'Other', label: 'Other', rows: 1, cards: 1, value: 2 },
  ]
  const row = (name, group) => ({ name, group })

  it('keeps server order and server totals; a group with no page rows is dropped', () => {
    const cards = [row('a', 'Creature'), row('b', 'Creature'), row('c', 'Creature'), row('d', 'Land')]
    const out = splitByGroup(cards, groups)
    expect(out.map(s => s.key)).toEqual(['Creature', 'Land'])
    expect(out[0].cards).toBe(5)
    expect(out[0].rows).toBe(3)
  })

  it('flags the group the page cut through, not complete ones', () => {
    const out = splitByGroup([row('a', 'Creature'), row('b', 'Creature'), row('c', 'Creature'), row('d', 'Land')], groups)
    expect(out.map(s => s.continues)).toEqual([false, true])
  })

  it('no groups returns one headerless section; no rows returns nothing', () => {
    const out = splitByGroup([row('a', undefined)], [])
    expect(out).toHaveLength(1)
    expect(out[0].headerless).toBe(true)
    expect(splitByGroup([], groups)).toEqual([])
    expect(splitByGroup(null, null)).toEqual([])
  })

  it('a row whose group the server did not list still renders', () => {
    const out = splitByGroup([row('a', 'Mystery')], groups)
    expect(out[0].key).toBe('Mystery')
    expect(out[0].pageRows).toHaveLength(1)
  })
})

describe('groupValueLabel', () => {
  it('shows an em dash for a zero-valued group with nothing priced', () => {
    expect(groupValueLabel({ value: 0, pageRows: [{ price: null }] })).toBe('—')
  })
  it('shows $0.00 when a visible row is priced at zero, and the money otherwise', () => {
    expect(groupValueLabel({ value: 0, pageRows: [{ price: 0 }] })).toBe('$0.00')
    expect(groupValueLabel({ value: 12.5, pageRows: [{ price: null }] })).toBe('$12.50')
  })
})
