import { describe, expect, it } from 'vitest'
import { cardColors, cardManaValue, groupCards, primaryType, qty } from './deckGrouping'

const card = (name, extra = {}) => ({ original_name: name, type_line: 'Instant', ...extra })

describe('card helpers', () => {
  it('derives colours from the cost, hybrids credit both halves', () => {
    expect(cardColors({ colors: null, mana_cost: '{2}{W/U}{B}' })).toEqual(['W', 'U', 'B'])
    expect(cardColors({ mana_cost: '{2/W}{G/P}' })).toEqual(['W', 'G'])
  })

  it('does not mutate the card colours array', () => {
    const colors = ['G', 'W']
    expect(cardColors({ colors })).toEqual(['W', 'G'])
    expect(colors).toEqual(['G', 'W'])
  })

  it('mana value from the cost when cmc is absent', () => {
    expect(cardManaValue({ cmc: undefined, mana_cost: '{X}{2/W}{G}' })).toBe(3)
    expect(cardManaValue({ mana_cost: '{W/U}{G/P}{C}' })).toBe(3)
    expect(cardManaValue({ cmc: '4' })).toBe(4)
    expect(cardManaValue({})).toBe(0)
  })

  it('type precedence and quantity', () => {
    expect(primaryType({ original_type_line: 'Artifact Land', type_line: 'Artifact Land' })).toBe('Land')
    expect(primaryType({ type_line: 'Artifact Creature — Golem' })).toBe('Creature')
    expect(qty({ quantity: '34' })).toBe(34)
    expect(qty({})).toBe(1)
  })
})

describe('groupCards', () => {
  const forest = card('Forest', { type_line: 'Basic Land — Forest', quantity: 34, colors: [] })
  const mindStone = card('Mind Stone', { type_line: 'Artifact', mana_cost: '{2}', cmc: 2, colors: [] })
  const bolt = card('Lightning Bolt', { mana_cost: '{R}', cmc: 1, colors: ['R'] })
  const charm = card('Boros Charm', { mana_cost: '{R}{W}', cmc: 2, colors: ['R', 'W'] })
  const titan = card('Ulamog', { type_line: 'Legendary Creature — Eldrazi', mana_cost: '{11}', cmc: 11, colors: [] })

  it('counts physical copies', () => {
    expect(groupCards([forest], 'color')).toEqual([{ key: 'land', label: 'Lands', cards: [forest], count: 34 }])
  })

  it('groups by colour in WUBRG then multi/colorless/land order', () => {
    const keys = groupCards([forest, charm, mindStone, bolt], 'color').map(g => g.key)
    expect(keys).toEqual(['R', 'multi', 'colorless', 'land'])
  })

  it('groups by mana value with 7+ and lands last', () => {
    const groups = groupCards([titan, forest, bolt], 'cmc')
    expect(groups.map(g => g.label)).toEqual(['MV 1', 'MV 7+', 'Lands'])
  })

  it('a multi-role card appears under each role; none comes last exactly once', () => {
    const roles = { 'mind stone': ['draw', 'ramp'], 'lightning bolt': ['removal', 'mystery_role'] }
    const groups = groupCards([mindStone, bolt, charm], 'role', roles)
    expect(groups.map(g => g.key)).toEqual(['ramp', 'draw', 'removal', 'mystery_role', 'none'])
    expect(groups.find(g => g.key === 'ramp').cards).toEqual([mindStone])
    expect(groups.find(g => g.key === 'none').cards).toEqual([charm])
  })

  it('role grouping before roles are measured is one honest group', () => {
    const groups = groupCards([bolt], 'role', null)
    expect(groups).toEqual([{ key: 'unmeasured', label: 'Roles not measured yet', cards: [bolt], count: 1 }])
  })

  it('type grouping pluralises and unknown modes fall back to type', () => {
    expect(groupCards([titan, forest], 'type').map(g => g.label)).toEqual(['Creatures', 'Lands'])
    expect(groupCards([titan], 'bogus').map(g => g.key)).toEqual(['Creature'])
  })
})
