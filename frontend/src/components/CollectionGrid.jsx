import { useState } from 'react'
import CardHover from './CardHover'
import CardFace, { SetChip } from './CardFace'
import CollectionEditBar from './CollectionEditBar'
import { TILE_SIZES } from '../utils/collectionView'

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
  text:   '#f5f5f4',
}

const badge = extra => ({
  position: 'absolute', top: 6, padding: '1px 7px', borderRadius: 6, fontSize: 11,
  fontWeight: 700, background: 'rgba(0,0,0,0.82)', border: `1px solid ${c.border}`,
  ...extra,
})

export default function CollectionGrid({ cards, onSetCount, onRemove, onPickPrinting,
                                         selectMode, selected, onToggleSelect, busy, size = 'm' }) {
  const [hovered, setHovered] = useState(null)
  const [flips, setFlips] = useState({})   // per-tile flip state, keyed by row_id
  const rows = cards || []
  const picked = selected || new Set()

  if (rows.length === 0) {
    return <div style={{ fontSize: 13, color: c.faint, padding: 20, textAlign: 'center' }}>
      Nothing to show.
    </div>
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${TILE_SIZES[size] || TILE_SIZES.m}px, 1fr))`,
                  gap: 12 }}>
      {rows.map(row => {
        const key = row.row_id   // a card owned in two printings/finishes is two rows
        const isSel = picked.has(key)
        const showBar = !selectMode && hovered === key
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
              <CardFace row={row} variant="full" flipped={!!flips[key]}
                onFlip={() => setFlips(f => ({ ...f, [key]: !f[key] }))} />

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
                <CollectionEditBar row={row} busy={busy} onSetCount={onSetCount}
                  onRemove={onRemove} onPickPrinting={onPickPrinting} />
              )}
            </div>

            <CardHover name={row.name}
              style={{ display: 'block', marginTop: 4, fontSize: 11.5, color: c.text,
                       overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {row.name}
            </CardHover>
            {row.set && (
              <div style={{ fontSize: 10, color: c.faint }}>
                <SetChip set={row.set} cn={row.cn} rarity={row.rarity} setName={row.set_name}
                  mismatch={row.printing_mismatch} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
