import { describe, it, expect } from 'vitest'
import { synergyRows } from './deckBreakdown'

describe('synergyRows', () => {
  it('maps a card with commander_synergy', () => {
    const rows = synergyRows([{
      name: 'Blasphemous Act',
      commander_synergy: { kind: 'damage_to_self_payoff', reason: 'r', one_sided: true, treasure: 13 },
    }])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toEqual({ name: 'Blasphemous Act', reason: 'r', oneSided: true, treasure: 13 })
  })

  it('ignores rows without the field (stale cache) and null', () => {
    expect(synergyRows([{ name: 'Sol Ring' }, { name: 'X', commander_synergy: null }])).toEqual([])
    expect(synergyRows(undefined)).toEqual([])
  })
})
