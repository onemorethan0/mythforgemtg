import { describe, it, expect } from 'vitest'
import { nextTab } from './tabsNav'

const KEYS = ['a', 'b', 'c']

describe('nextTab', () => {
  it('moves right and left', () => {
    expect(nextTab(KEYS, 'a', 'ArrowRight')).toBe('b')
    expect(nextTab(KEYS, 'c', 'ArrowLeft')).toBe('b')
  })
  it('wraps at both ends', () => {
    expect(nextTab(KEYS, 'c', 'ArrowRight')).toBe('a')
    expect(nextTab(KEYS, 'a', 'ArrowLeft')).toBe('c')
  })
  it('jumps to the ends with Home and End', () => {
    expect(nextTab(KEYS, 'b', 'Home')).toBe('a')
    expect(nextTab(KEYS, 'b', 'End')).toBe('c')
  })
  it('ignores other keys', () => {
    expect(nextTab(KEYS, 'b', 'Enter')).toBe('b')
  })
  it('falls back to the first tab when the current one is unknown', () => {
    expect(nextTab(KEYS, 'zzz', 'ArrowRight')).toBe('a')
  })
})
