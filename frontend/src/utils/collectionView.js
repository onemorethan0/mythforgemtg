// View-settings model for the collection manager. Pure: no React, no globals — the
// storage object is passed in, so every failure mode (bad JSON, a throwing storage,
// a field of the wrong type) is testable in plain node.

export const VIEW_MODES = ['list', 'compact', 'grid', 'tiles', 'stacks']

// Mirrors collection_index.GROUP_BYS.
export const GROUP_BYS = ['none', 'type', 'color', 'cmc', 'rarity', 'set', 'finish', 'card']

// Mirrors the backend sort keys.
export const SORT_KEYS = [
  ['name', 'Name'], ['value', 'Value'], ['price', 'Price'], ['count', 'Copies'],
  ['cmc', 'Mana value'], ['type', 'Type'], ['set', 'Set'], ['edhrec', 'Popularity'],
  ['rarity', 'Rarity'], ['color', 'Color'], ['released', 'Release date'],
  ['collector', 'Collector number'], ['added', 'Date added'], ['finish', 'Finish'],
]

// Column minimum width in px for the image-grid modes.
export const TILE_SIZES = { s: 120, m: 160, l: 220 }

export const LIST_COLUMNS = ['set', 'cn', 'finish', 'rarity', 'type', 'cmc', 'mana', 'price',
                             'value', 'added', 'condition', 'language']

export const DEFAULT_VIEW = {
  mode: 'list', size: 'm', groupBy: 'none', sort: 'name', direction: 'asc',
  then: null, thenDirection: 'asc', columns: ['set', 'finish', 'type', 'price'], collapsed: {},
}

const KEY = 'mtg_coll_view_v2'
const LEGACY_KEY = 'mtg_coll_view'   // 'list' | 'grid'

const SORT_NAMES = SORT_KEYS.map(([k]) => k)
const DIRECTIONS = ['asc', 'desc']

const oneOf = (v, allowed, fallback) => (allowed.includes(v) ? v : fallback)

const cleanColumns = v => {
  if (!Array.isArray(v)) return [...DEFAULT_VIEW.columns]
  const out = []
  for (const col of v) if (LIST_COLUMNS.includes(col) && !out.includes(col)) out.push(col)
  return out
}

// collapsed is { [groupBy]: [group key, ...] }: collapsing "Creature" under Type must not
// collapse an unrelated group that happens to share a key under another grouping. A
// wrong shape anywhere costs only that entry.
const cleanCollapsed = v => {
  const out = {}
  if (!v || typeof v !== 'object' || Array.isArray(v)) return out
  for (const by of GROUP_BYS) {
    if (by === 'none' || !Array.isArray(v[by])) continue
    const keys = []
    for (const k of v[by]) if (typeof k === 'string' && !keys.includes(k)) keys.push(k)
    if (keys.length) out[by] = keys
  }
  return out
}

// Every field is validated on its own, so one bad field costs only itself.
function sanitize(raw) {
  const r = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}
  return {
    mode: oneOf(r.mode, VIEW_MODES, DEFAULT_VIEW.mode),
    size: oneOf(r.size, Object.keys(TILE_SIZES), DEFAULT_VIEW.size),
    groupBy: oneOf(r.groupBy, GROUP_BYS, DEFAULT_VIEW.groupBy),
    sort: oneOf(r.sort, SORT_NAMES, DEFAULT_VIEW.sort),
    direction: oneOf(r.direction, DIRECTIONS, DEFAULT_VIEW.direction),
    then: oneOf(r.then, SORT_NAMES, null),
    thenDirection: oneOf(r.thenDirection, DIRECTIONS, DEFAULT_VIEW.thenDirection),
    columns: cleanColumns(r.columns),
    collapsed: cleanCollapsed(r.collapsed),
  }
}

// Never throws: any storage error or unparseable value yields the defaults (or whatever
// part of the value is valid).
export function loadViewSettings(storage) {
  try {
    const raw = storage.getItem(KEY)
    if (raw != null) return sanitize(JSON.parse(raw))
    const legacy = storage.getItem(LEGACY_KEY)
    return sanitize({ mode: legacy === 'grid' || legacy === 'list' ? legacy : undefined })
  } catch {
    return sanitize(null)
  }
}

export function saveViewSettings(storage, settings) {
  try {
    storage.setItem(KEY, JSON.stringify(settings))
  } catch {
    // Storage can be unavailable or full; the view simply won't persist.
  }
}

// Query-string pairs for the server-side part of the view.
export function viewQuery(s) {
  const q = [['sort', s.sort], ['direction', s.direction]]
  if (s.then) { q.push(['then', s.then]); q.push(['then_direction', s.thenDirection]) }
  const by = effectiveGroupBy(s)
  if (by && by !== 'none') q.push(['group', by])
  return q
}

// Stacks draws one column per group, so it needs a grouping even when the user picked
// none: it falls back to the card type.
export function effectiveGroupBy(s) {
  const by = s.groupBy || 'none'
  return by === 'none' && s.mode === 'stacks' ? 'type' : by
}

// Cut `rows` (server order: already ordered by group) into the groups they belong to, in
// order, pairing each with the server's whole-set totals. A group in `groups` with no row
// on this page is left out; `pageRows` vs the server's `rows` says whether a group
// continues past the page. With no groups at all the rows come back as one headerless
// section, so a missing `groups` never hides cards.
export function splitByGroup(cards, groups) {
  const rows = cards || []
  if (!groups || groups.length === 0) {
    return rows.length ? [{ key: '', label: '', pageRows: rows, rows: rows.length, cards: null,
                            value: null, continues: false, headerless: true }] : []
  }
  const totals = new Map(groups.map(g => [g.key, g]))
  const out = []
  const byKey = new Map()
  for (const row of rows) {
    let sec = byKey.get(row.group)
    if (!sec) {
      const t = totals.get(row.group) ||
        { key: row.group, label: String(row.group ?? ''), rows: 0, cards: 0, value: 0 }
      sec = { ...t, pageRows: [], continues: false }
      byKey.set(row.group, sec)
      out.push(sec)
    }
    sec.pageRows.push(row)
  }
  for (const sec of out) sec.continues = sec.pageRows.length < sec.rows
  return out
}

// "$12.34" for a priced group, "—" when the group's value is zero and none of the rows
// we can see carry a price (an unpriced group is not a worthless one).
export function groupValueLabel(sec) {
  const v = Number(sec.value) || 0
  if (v === 0 && !sec.pageRows.some(r => typeof r.price === 'number')) return '—'
  return `$${v.toFixed(2)}`
}

const MANA = { W: '#f8f0d8', U: '#4a90d9', B: '#5b5254', R: '#d94a4a', G: '#4aa563',
               Multicolor: '#c9a227', Colorless: '#8a8a8a' }

// Colour-identity dot for a row; null while the row is unresolved (no colour data yet).
export const dotColor = row => {
  const colors = row.colors || []
  if (!row.resolved) return null
  if (colors.length > 1) return MANA.Multicolor
  return MANA[colors[0]] || MANA.Colorless
}

// One owned printing as a decklist line the importer reads back unchanged:
//   3x Sol Ring (C21) 263 *F*
// Foil -> " *F*", etched -> " *E*"; " (SET) CN" is omitted when the set is unknown and
// " CN" when the collector number is blank.
export function decklistLine(row) {
  let line = `${row.count}x ${row.name}`
  const set = String(row.set || '').trim()
  if (set) {
    line += ` (${set.toUpperCase()})`
    const cn = String(row.cn || '').trim()
    if (cn) line += ` ${cn}`
  }
  if (row.finish === 'foil') line += ' *F*'
  else if (row.finish === 'etched') line += ' *E*'
  return line
}
