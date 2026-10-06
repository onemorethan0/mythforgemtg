import { useState } from 'react'
import { List, Rows3, LayoutGrid, Grid3x3, Layers } from 'lucide-react'
import { VIEW_MODES, GROUP_BYS, SORT_KEYS, TILE_SIZES, LIST_COLUMNS } from '../utils/collectionView'

// The view controls row of the collection manager: mode, tile size, group, sort,
// then-by, direction toggles, columns, and the Filters / Select toggles. Renders a
// fragment so the parent's flex row can put its search box on the same line.

const c = {
  gold:   '#eab308',
  dim:    '#a8a29e',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
}

const MODE_META = {
  list:    [List, 'List'],
  compact: [Rows3, 'Compact list'],
  grid:    [LayoutGrid, 'Binder'],
  tiles:   [Grid3x3, 'Tiles'],
  stacks:  [Layers, 'Stacks'],
}

const GROUP_LABELS = {
  none: 'No grouping', type: 'Type', color: 'Color', cmc: 'Mana value', rarity: 'Rarity',
  set: 'Set', finish: 'Finish', card: 'Card',
}

const COLUMN_LABELS = {
  set: 'Set', cn: 'Collector #', finish: 'Finish', rarity: 'Rarity', type: 'Type',
  cmc: 'Mana value', mana: 'Mana cost', price: 'Price', value: 'Value', added: 'Date added',
  condition: 'Condition', language: 'Language',
}

const GRID_MODES = ['grid', 'tiles', 'stacks']

const btn = (extra = {}) => ({
  padding: '8px 14px', borderRadius: 8, cursor: 'pointer',
  background: c.card, border: `1px solid ${c.border}`, color: c.dim,
  fontFamily: 'inherit', fontSize: 13, ...extra,
})

const active = { background: '#1c1410', border: `1px solid ${c.gold}`, color: c.gold, fontWeight: 700 }

const selectStyle = {
  padding: '9px 10px', borderRadius: 8, background: c.panel,
  border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'inherit', fontSize: 13,
}

export default function CollectionToolbar({ settings, onChange, filtersActive, onToggleFilters,
                                            selectMode, onToggleSelect }) {
  const [colsOpen, setColsOpen] = useState(false)
  const { mode, size, groupBy, sort, direction, then, thenDirection, columns } = settings

  const flip = d => (d === 'asc' ? 'desc' : 'asc')

  return (
    <>
      {/* Mode switcher: icon-only, a one-click switch rather than a dropdown. */}
      <div style={{ display: 'flex', borderRadius: 8, overflow: 'hidden', border: `1px solid ${c.border}` }}>
        {VIEW_MODES.map(m => {
          const [Icon, label] = MODE_META[m]
          return (
            <button key={m} onClick={() => onChange({ mode: m })} title={`${label} view`}
              aria-label={`${label} view`} aria-pressed={mode === m}
              style={{ padding: '8px 11px', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                       display: 'flex', alignItems: 'center',
                       background: mode === m ? '#1c1410' : c.card,
                       color: mode === m ? c.gold : c.dim }}>
              <Icon size={16} />
            </button>
          )
        })}
      </div>

      {GRID_MODES.includes(mode) && (
        <div style={{ display: 'flex', borderRadius: 8, overflow: 'hidden', border: `1px solid ${c.border}` }}
          title="Tile size">
          {Object.keys(TILE_SIZES).map(k => (
            <button key={k} onClick={() => onChange({ size: k })} aria-pressed={size === k}
              style={{ padding: '8px 11px', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                       fontSize: 12.5, fontWeight: 700,
                       background: size === k ? '#1c1410' : c.card,
                       color: size === k ? c.gold : c.dim }}>
              {k.toUpperCase()}
            </button>
          ))}
        </div>
      )}

      <select value={groupBy} onChange={e => onChange({ groupBy: e.target.value })}
        title="Group by" aria-label="Group by" style={selectStyle}>
        {GROUP_BYS.map(g => <option key={g} value={g}>{g === 'none' ? 'Group: none' : `Group: ${GROUP_LABELS[g]}`}</option>)}
      </select>

      <select value={sort} onChange={e => onChange({ sort: e.target.value })}
        title="Sort by" aria-label="Sort by" style={selectStyle}>
        {SORT_KEYS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
      <button onClick={() => onChange({ direction: flip(direction) })}
        title={direction === 'asc' ? 'Ascending' : 'Descending'} style={btn({ padding: '8px 12px' })}>
        {direction === 'asc' ? '↑' : '↓'}
      </button>

      <select value={then || ''} onChange={e => onChange({ then: e.target.value || null })}
        title="Then sort by" aria-label="Then sort by" style={selectStyle}>
        <option value="">Then by: none</option>
        {SORT_KEYS.map(([v, label]) => <option key={v} value={v}>{`Then by: ${label}`}</option>)}
      </select>
      {then && (
        <button onClick={() => onChange({ thenDirection: flip(thenDirection) })}
          title={thenDirection === 'asc' ? 'Then ascending' : 'Then descending'}
          style={btn({ padding: '8px 12px' })}>
          {thenDirection === 'asc' ? '↑' : '↓'}
        </button>
      )}

      {mode === 'list' && (
        <div style={{ position: 'relative' }}>
          <button onClick={() => setColsOpen(v => !v)} style={btn(colsOpen ? active : {})}
            aria-expanded={colsOpen}>
            Columns ▾
          </button>
          {colsOpen && (
            <div style={{ position: 'absolute', top: '100%', right: 0, zIndex: 20, marginTop: 4,
                          background: c.card, border: `1px solid ${c.border}`, borderRadius: 8,
                          padding: 8, minWidth: 160, boxShadow: '0 6px 20px rgba(0,0,0,0.5)' }}>
              {LIST_COLUMNS.map(col => (
                <label key={col} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 4px',
                                          fontSize: 12.5, color: c.dim, cursor: 'pointer' }}>
                  <input type="checkbox" checked={columns.includes(col)}
                    onChange={() => onChange({
                      columns: columns.includes(col)
                        ? columns.filter(x => x !== col)
                        : LIST_COLUMNS.filter(x => x === col || columns.includes(x)),
                    })} />
                  {COLUMN_LABELS[col]}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <button onClick={onToggleFilters} style={btn(filtersActive ? active : {})}>
        ⚗ Filters{filtersActive ? ' •' : ''}
      </button>
      <button onClick={onToggleSelect} title="Select several cards and act on them at once"
        style={btn(selectMode ? active : {})}>
        ☑ Select
      </button>
    </>
  )
}
