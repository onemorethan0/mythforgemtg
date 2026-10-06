import CardHover from './CardHover'

// List view of the collection: one row per owned printing, columns driven by the view
// settings. Rows are identified by the server's `row_id` — a card owned in two sets,
// or in two finishes, is two rows, so the name alone is not an identity.

const c = {
  gold:   '#eab308',
  dim:    '#a8a29e',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
}

const MANA = { W: '#f8f0d8', U: '#4a90d9', B: '#5b5254', R: '#d94a4a', G: '#4aa563',
               Multicolor: '#c9a227', Colorless: '#8a8a8a' }

const btn = (busy, extra = {}) => ({
  padding: '8px 14px', borderRadius: 8, cursor: busy ? 'wait' : 'pointer',
  background: c.card, border: `1px solid ${c.border}`, color: c.dim,
  fontFamily: 'inherit', fontSize: 13, ...extra,
})

const money = n => `$${n.toFixed(2)}`

const cellText = { fontSize: 11, color: c.faint, flexShrink: 0, overflow: 'hidden',
                   whiteSpace: 'nowrap', textAlign: 'right' }

// Left-to-right order of the optional columns (independent of the order they were ticked in).
const ORDER = ['type', 'cmc', 'mana', 'rarity', 'set', 'cn', 'finish', 'condition',
               'language', 'added', 'price', 'value']

export default function CollectionList({ cards, columns, selectMode, selected, onToggleSelect,
                                         onSetCount, onRemove, onPickPrinting, busy }) {
  const rows = cards || []
  const show = ORDER.filter(col => (columns || []).includes(col))
  const has = col => show.includes(col)

  const renderColumn = (col, row) => {
    switch (col) {
      case 'type':
        // The list has always shown the mana value beside the type; keep that unless the
        // dedicated Mana value column is on, so the number never appears twice.
        return (
          <span key={col} title={row.resolved ? `Mana value ${row.cmc}` : ''}
            style={{ ...cellText, minWidth: 46 }}>
            {row.resolved ? `${row.type || ''}${has('cmc') ? '' : ` ${row.cmc}`}` : ''}
          </span>
        )
      case 'cmc':
        return <span key={col} style={{ ...cellText, minWidth: 22 }}>{row.resolved ? row.cmc : ''}</span>
      case 'mana':
        return <span key={col} style={{ ...cellText, minWidth: 64, fontFamily: 'monospace' }}>{row.mana_cost || ''}</span>
      case 'rarity':
        return <span key={col} style={{ ...cellText, minWidth: 54 }}>{row.rarity || ''}</span>
      case 'set':
        // The set chip IS the printing control. A row with no printing reads as "set?"
        // rather than a dash, because it's an invitation, not a value.
        return (
          <button key={col} onClick={() => onPickPrinting(row)} disabled={busy}
            title={row.set ? `${row.set}${row.cn ? ` #${row.cn}` : ''} — click to change printing`
                           : 'Printing unknown — click to choose one'}
            style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', flexShrink: 0,
              padding: '1px 6px', borderRadius: 4, minWidth: 44, textAlign: 'center',
              fontFamily: 'inherit', cursor: busy ? 'wait' : 'pointer',
              background: row.set ? c.panel : 'transparent',
              border: `1px solid ${row.set ? c.border : '#3f3a2a'}`,
              color: row.set ? c.dim : '#a16207' }}>
            {row.set || 'set?'}
          </button>
        )
      case 'cn':
        return <span key={col} style={{ ...cellText, minWidth: 34 }}>{row.cn || ''}</span>
      case 'finish':
        return (
          <span key={col} style={{ ...cellText, minWidth: 40,
                                   color: row.finish && row.finish !== 'nonfoil' ? '#fbbf24' : c.faint }}>
            {row.finish && row.finish !== 'nonfoil' ? row.finish : ''}
          </span>
        )
      case 'condition':
        return <span key={col} style={{ ...cellText, minWidth: 26 }}>{row.condition || ''}</span>
      case 'language':
        return <span key={col} style={{ ...cellText, minWidth: 22 }}>{row.lang || ''}</span>
      case 'added':
        return <span key={col} style={{ ...cellText, minWidth: 74 }}>{row.date_added || ''}</span>
      case 'price':
        // Market price for this printing (x count shown on hover).
        return (
          <span key={col}
            title={row.price ? `${money(row.price)} each · ${money(row.price * row.count)} for ${row.count}` : 'No price yet — hit Get prices'}
            style={{ fontSize: 11.5, color: row.price ? '#4ade80' : c.faint, minWidth: 52,
                     textAlign: 'right', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
            {row.price ? money(row.price) : '—'}
          </span>
        )
      case 'value':
        return (
          <span key={col} title={row.price ? `${money(row.price)} × ${row.count}` : 'No price yet'}
            style={{ fontSize: 11.5, color: row.price ? '#4ade80' : c.faint, minWidth: 58,
                     textAlign: 'right', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
            {row.price ? money(row.price * row.count) : '—'}
          </span>
        )
      default:
        return null
    }
  }

  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: 10, overflow: 'hidden' }}>
      {rows.map((row, i) => (
        <div key={row.row_id} style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
          background: i % 2 ? '#141210' : c.card, borderBottom: i < rows.length - 1 ? `1px solid ${c.border}` : 'none',
        }}>
          {selectMode && (
            <input type="checkbox" checked={selected.has(row.row_id)}
              onChange={() => onToggleSelect(row)} style={{ flexShrink: 0, margin: 0 }} />
          )}
          {/* Colour identity dot — the fastest read of "what is this card" in a list
              this long. An unrecognized row gets a hollow dot rather than a wrong one. */}
          <span title={row.resolved ? `${row.type_line || row.type}${row.mana_cost ? ` · ${row.mana_cost}` : ''}`
                                    : 'Not recognized — check the name'}
            style={{ width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
              background: !row.resolved ? 'transparent'
                : (row.colors || []).length > 1 ? MANA.Multicolor
                : MANA[(row.colors || [])[0]] || MANA.Colorless,
              border: row.resolved ? 'none' : `1px solid ${c.faint}` }} />
          <CardHover name={row.name} style={{ flex: 1, fontSize: 13.5, color: '#f5f5f4', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
            {row.name}
          </CardHover>
          {row.game_changer && (
            <span title="Official WotC Game Changer" style={{
              fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 5,
              flexShrink: 0, color: '#fbbf24', border: '1px solid #d97706',
              background: '#78350f22',
            }}>⚡ GC</span>
          )}
          {show.map(col => renderColumn(col, row))}
          <button onClick={() => onSetCount(row, row.count - 1)} disabled={busy} style={btn(busy, { padding: '2px 10px', fontSize: 16 })}>−</button>
          <span style={{ minWidth: 26, textAlign: 'center', fontSize: 13.5, color: c.gold, fontWeight: 700 }}>{row.count}</span>
          <button onClick={() => onSetCount(row, row.count + 1)} disabled={busy} style={btn(busy, { padding: '2px 10px', fontSize: 16 })}>+</button>
          <button onClick={() => onRemove(row)} disabled={busy}
            style={btn(busy, { padding: '2px 10px', color: '#f87171', border: '1px solid #3f1d1d' })} title="Remove this printing">✕</button>
        </div>
      ))}
    </div>
  )
}
