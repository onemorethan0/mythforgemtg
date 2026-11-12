import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = rel => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')

// The palette is copied from the literals the screens already use, so a phase-0 swap to variables
// cannot change a colour. Pinned here so a drift shows up as a failing test, not a subtle repaint.
const EXPECTED = {
  '--surface-0': '#0c0a09', '--surface-1': '#1c1917', '--surface-2': '#292524', '--border': '#44403c',
  '--text': '#f5f5f4', '--text-muted': '#a8a29e', '--text-faint': '#78716c',
  '--accent': '#eab308', '--accent-strong': '#ca8a04', '--accent-bg': '#422006', '--accent-text': '#fde047',
  '--ok': '#86efac', '--ok-strong': '#15803d', '--ok-bg': '#052e16',
  '--bad': '#fca5a5', '--bad-strong': '#b91c1c', '--bad-bg': '#450a0a',
  '--info': '#93c5fd', '--info-strong': '#1d4ed8', '--info-bg': '#1e3a5f',
  '--warn': '#fcd34d',
  '--space-1': '4px', '--space-2': '8px', '--space-3': '12px', '--space-4': '16px', '--space-6': '24px',
  '--radius-sm': '6px', '--radius-md': '8px', '--radius-lg': '10px',
  '--text-xs': '11px', '--text-sm': '12px', '--text-md': '13px', '--text-lg': '16px',
}

describe('design tokens', () => {
  const css = read('./tokens.css')

  it('define the palette, spacing, radii and type scale', () => {
    for (const [name, value] of Object.entries(EXPECTED)) {
      expect(css, name).toMatch(new RegExp(`${name}:\\s*${value.replace('#', '#')}\\s*;`))
    }
  })

  it('declare nothing but the expected variables', () => {
    const declared = [...css.matchAll(/^\s*(--[a-z0-9-]+):/gm)].map(m => m[1]).sort()
    expect(declared).toEqual(Object.keys(EXPECTED).sort())
  })

  it('are imported by index.css', () => {
    expect(read('../index.css')).toContain("@import './styles/tokens.css'")
  })
})
