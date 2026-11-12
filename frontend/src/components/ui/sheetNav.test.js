import { describe, it, expect } from 'vitest'
import { sheetTabAction } from './sheetNav'

describe('sheetTabAction', () => {
  it('opens the sheet on the tapped tab when it is closed', () => {
    expect(sheetTabAction('analyze', 'upgrade', false)).toEqual({ tab: 'upgrade', open: true })
    expect(sheetTabAction('analyze', 'analyze', false)).toEqual({ tab: 'analyze', open: true })
  })
  it('folds the sheet away when the open tab is tapped again', () => {
    expect(sheetTabAction('analyze', 'analyze', true)).toEqual({ tab: 'analyze', open: false })
  })
  it('switches tabs without closing when another tab is tapped', () => {
    expect(sheetTabAction('analyze', 'mentor', true)).toEqual({ tab: 'mentor', open: true })
  })
})
