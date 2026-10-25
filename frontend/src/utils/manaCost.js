// Mana-cost helpers shared by the single-card designer (moved out of StepSingleCard.jsx so
// that file exports only components, which React Fast Refresh requires).
const WUBRG = ['W', 'U', 'B', 'R', 'G']

// A cost typed without braces ("2WU") is unambiguous, so show the user what it
// will become rather than silently producing a colourless, pip-less card. Mirrors
// server._normalize_mana_cost — keep the two in step.
const SHORTHAND_MANA = /\d+|[WUBRGCXYZS]/gi
export function normalizeManaCost(raw) {
  const s = (raw || '').trim()
  if (!s || s.includes('{')) return s
  const compact = s.replace(/[\s/]/g, '')
  if (!compact) return s
  const parts = compact.match(SHORTHAND_MANA) || []
  if (parts.join('') !== compact) return s
  return parts.map(p => `{${p.toUpperCase()}}`).join('')
}

// Colour identity implied by a mana cost, so the preview frame matches what the
// backend will derive when the user hasn't pinned colours by hand.
export function colorsFromCost(cost) {
  const out = []
  for (const m of (normalizeManaCost(cost).match(/\{([^}]+)\}/g) || [])) {
    for (const L of WUBRG) if (m.toUpperCase().includes(L) && !out.includes(L)) out.push(L)
  }
  return WUBRG.filter(c => out.includes(c))
}
