import { describe, it, expect } from 'vitest'
import { bracketSummary, measureSummary, breakdownSummary, statsSummary } from './deckSummaries'

describe('bracketSummary / measureSummary', () => {
  const sim = { power_profile: { bracket_estimate: 2, bracket_label: 'Core' } }
  it('names the bracket', () => {
    expect(bracketSummary(sim)).toBe('Bracket 2 (Core)')
    expect(bracketSummary({ power_profile: { bracket_estimate: 3 } })).toBe('Bracket 3')
  })
  it('says nothing when there is no measurement', () => {
    expect(bracketSummary(null)).toBeNull()
    expect(bracketSummary({})).toBeNull()
    expect(bracketSummary({ power_profile: {} })).toBeNull()
    expect(measureSummary(undefined)).toBeNull()
  })
  it('adds when it was measured', () => {
    expect(measureSummary({ simulation: sim, date: '2026-11-09T13:48:37' })).toBe('Bracket 2 (Core) · measured Nov 9')
    expect(measureSummary({ simulation: sim })).toBe('Bracket 2 (Core)')
    expect(measureSummary({ simulation: sim, date: 'garbage' })).toBe('Bracket 2 (Core)')
  })
})

describe('breakdownSummary', () => {
  it('is honest before the breakdown has run', () => {
    expect(breakdownSummary(null)).toBe('not measured yet')
    expect(breakdownSummary({ roles: {} })).toBe('not measured yet')
  })
  it('names up to three under-target roles', () => {
    expect(breakdownSummary({ roles: { under_target: ['draw', 'noncreature_removal'] } }))
      .toBe('2 roles under target: draw, noncreature removal')
    expect(breakdownSummary({ roles: { under_target: ['a', 'b', 'c', 'd'] } }))
      .toBe('4 roles under target: a, b, c…')
    expect(breakdownSummary({ roles: { under_target: ['ramp'] } })).toBe('1 role under target: ramp')
  })
  it('says so when nothing is under target', () => {
    expect(breakdownSummary({ roles: { under_target: [] } })).toBe('every core role at its typical count')
  })
})

describe('statsSummary', () => {
  it('reads the average mana value and the lands', () => {
    expect(statsSummary({ average_cmc: 3.5, type_counts: { Land: 37 } })).toBe('Avg MV 3.5 · 37 lands')
    expect(statsSummary({ avg_cmc: 2.04, type_counts: { Land: 1 } })).toBe('Avg MV 2.0 · 1 land')
  })
  it('copes with missing parts', () => {
    expect(statsSummary(null)).toBeNull()
    expect(statsSummary({})).toBeNull()
    expect(statsSummary({ type_counts: { Land: 36 } })).toBe('36 lands')
  })
})
