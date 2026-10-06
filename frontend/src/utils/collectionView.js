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

const cleanCollapsed = v => {
  const out = {}
  if (v && typeof v === 'object' && !Array.isArray(v))
    for (const [k, on] of Object.entries(v)) if (on === true) out[k] = true
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
  if (s.groupBy && s.groupBy !== 'none') q.push(['group', s.groupBy])
  return q
}
