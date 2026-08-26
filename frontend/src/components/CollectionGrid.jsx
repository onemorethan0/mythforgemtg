import { useState } from 'react'
import CardHover from './CardHover'

// Binder view of the collection: one tile per owned printing, showing the real card.
// Counts, price and the edit controls ride on the tile so the art stays the thing you
// read. Images come from the local card store, so a full page of tiles costs no network.

const c = {
  gold:   '#eab308',
  green:  '#4ade80',
  dim:    '#a8a29e',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
  text:   '#f5f5f4',
}

const MANA = { W: '#f8f0d8', U: '#4a90d9', B: '#5b5254', R: '#d94a4a', G: '#4aa563',
               Multicolor: '#c9a227', Colorless: '#8a8a8a' }

// A card owned in two sets is two rows, so the name alone is not an identity.
const rowKey = r => `${r.name}|${r.set || ''}|${r.cn || ''}`

const dotColor = row => {
  const colors = row.colors || []
  if (!row.resolved) return null
  if (colors.length > 1) return MANA.Multicolor
  return MANA[colors[0]] || MANA.Colorless
}

const badge = extra => ({
  position: 'absolute', top: 6, padding: '1px 7px', borderRadius: 6, fontSize: 11,
  fontWeight: 700, background: 'rgba(0,0,0,0.82)', border: `1px solid ${c.border}`,
  ...extra,
})

export default function CollectionGrid({ cards, onSetCount, onRemove, onPickPrinting,
                                         selectMode, selected, onToggleSelect, busy }) {
  const [hovered, setHovered] = useState(null)
  const rows = cards || []
  const picked = selected || new Set()

  if (rows.length === 0) {
    return <div style={{ fontSize: 13, color: c.faint, padding: 20, textAlign: 'center' }}>
      Nothing to show.
    </div>
  }

  const ctl = (extra = {}) => ({
    padding: '1px 7px', borderRadius: 6, fontSize: 12, background: c.card,
    border: `1px solid ${c.border}`, color: c.dim, fontFamily: 'inherit',
    cursor: busy ? 'wait' : 'pointer', ...extra,
  })

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
                  gap: 12 }}>
      {rows.map(row => {
        const key = rowKey(row)
        const isSel = picked.has(key)
        const showBar = !selectMode && hovered === key
        const dot = dotColor(row)
        return (
          <div key={key}
            onMouseEnter={() => setHovered(key)}
            onMouseLeave={() => setHovered(h => (h === key ? null : h))}
            onClick={selectMode ? () => onToggleSelect && onToggleSelect(row) : undefined}
            style={{ cursor: selectMode ? 'pointer' : 'default' }}>

            <div style={{ position: 'relative', aspectRatio: '488 / 680', borderRadius: 10,
                          overflow: 'hidden', background: c.card,
                          // Selection reads as a ring, never as an overlay — hiding the art
                          // would defeat the point of a binder.
                          border: `${isSel ? 2 : 1}px solid ${isSel ? c.gold : c.border}` }}>
              {row.image ? (
                <img src={row.image} alt={row.name} loading="lazy"
                  style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
              ) : (
                <div style={{ width: '100%', height: '100%', background: c.panel, padding: 8,
                              boxSizing: 'border-box', display: 'flex', flexDirection: 'column',
                              alignItems: 'center', justifyContent: 'center', gap: 6,
                              textAlign: 'center', overflow: 'hidden' }}>
                  <span style={{ width: 14, height: 14, borderRadius: '50%',
                                 background: dot || 'transparent',
                                 border: dot ? 'none' : `1px solid ${c.faint}` }} />
                  <span style={{ fontSize: 11.5, color: c.dim }}>{row.name}</span>
                  {row.type && <span style={{ fontSize: 10, color: c.faint }}>{row.type}</span>}
                </div>
              )}

              {selectMode && (
                <span style={badge({ left: 6, padding: '2px 5px', background: 'rgba(0,0,0,0.82)' })}>
                  <input type="checkbox" checked={isSel} readOnly
                    style={{ display: 'block', margin: 0, pointerEvents: 'none' }} />
                </span>
              )}
              {row.count > 1 && (
                <span style={badge({ left: selectMode ? 34 : 6, color: c.gold })}>x{row.count}</span>
              )}
              {typeof row.price === 'number' && (
                <span style={badge({ right: 6, color: c.green })}>${row.price.toFixed(2)}</span>
              )}
              {/* `game_changer` has been enriched onto every row all along (the same flag
                  the S21 bracket work made visible in the strength panel) but never shown
                  here — a player deciding what to keep sleeved wants to know which of
                  their own cards are on the official list. Bottom-left: top corners are
                  already spoken for by the count/price badges. */}
              {row.game_changer && (
                <span title="Official WotC Game Changer"
                  style={badge({ left: 6, bottom: 6, top: 'auto', color: '#fbbf24',
                                 border: '1px solid #d97706' })}>
                  ⚡ GC
                </span>
              )}

              {showBar && (
                <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0,
                              background: 'rgba(0,0,0,0.86)', padding: 6, display: 'flex',
                              gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                  <button disabled={busy} title="One fewer" style={ctl()}
                    onClick={() => onSetCount && onSetCount(row, row.count - 1)}>−</button>
                  <span style={{ color: c.gold, fontWeight: 700, minWidth: 18, textAlign: 'center',
                                 fontSize: 12 }}>{row.count}</span>
                  <button disabled={busy} title="One more" style={ctl()}
                    onClick={() => onSetCount && onSetCount(row, row.count + 1)}>+</button>
                  {onPickPrinting && (
                    <button disabled={busy} title="Choose printing" style={ctl()}
                      onClick={() => onPickPrinting(row)}>🖨</button>
                  )}
                  <button disabled={busy} title="Remove" style={ctl({ color: '#f87171' })}
                    onClick={() => onRemove && onRemove(row)}>✕</button>
                </div>
              )}
            </div>

            <CardHover name={row.name}
              style={{ display: 'block', marginTop: 4, fontSize: 11.5, color: c.text,
                       overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {row.name}
            </CardHover>
            {row.set && <div style={{ fontSize: 10, color: c.faint }}>{row.set}</div>}
          </div>
        )
      })}
    </div>
  )
}
