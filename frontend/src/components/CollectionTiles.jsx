import { useState } from 'react'
import CardHover from './CardHover'
import CardFace, { SetChip } from './CardFace'
import CollectionEditBar from './CollectionEditBar'
import ManaCost from './ManaCost'
import { TILE_SIZES } from '../utils/collectionView'

// Art-tile view: a 16:10 art_crop banner per owned printing with the name, cost, type, set,
// count and price beneath. Same props and edit controls as CollectionGrid; the tile is
// wider than a card so it scales the grid's column minimum up.

const WIDTH_FACTOR = 1.6

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

export default function CollectionTiles({ cards, onSetCount, onRemove, onPickPrinting,
                                          selectMode, selected, onToggleSelect, busy, size = 'm' }) {
  const [hovered, setHovered] = useState(null)
  const rows = cards || []
  const picked = selected || new Set()

  if (rows.length === 0) {
    return <div style={{ fontSize: 13, color: c.faint, padding: 20, textAlign: 'center' }}>
      Nothing to show.
    </div>
  }

  const min = Math.round((TILE_SIZES[size] || TILE_SIZES.m) * WIDTH_FACTOR)

  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))`,
                  gap: 12 }}>
      {rows.map(row => {
        const key = row.row_id
        const isSel = picked.has(key)
        const showBar = !selectMode && hovered === key
        return (
          <div key={key}
            onMouseEnter={() => setHovered(key)}
            onMouseLeave={() => setHovered(h => (h === key ? null : h))}
            onClick={selectMode ? () => onToggleSelect && onToggleSelect(row) : undefined}
            style={{ cursor: selectMode ? 'pointer' : 'default', background: c.card,
                     borderRadius: 10, overflow: 'hidden', minWidth: 0,
                     border: `${isSel ? 2 : 1}px solid ${isSel ? c.gold : c.border}` }}>

            <div style={{ position: 'relative', aspectRatio: '16 / 10' }}>
              <CardFace row={row} variant="art" />
              {selectMode && (
                <span style={badge({ left: 6, padding: '2px 5px' })}>
                  <input type="checkbox" checked={isSel} readOnly
                    style={{ display: 'block', margin: 0, pointerEvents: 'none' }} />
                </span>
              )}
              {row.game_changer && (
                <span title="Official WotC Game Changer"
                  style={badge({ right: 6, color: '#fbbf24', border: '1px solid #d97706' })}>
                  ⚡ GC
                </span>
              )}
              {showBar && (
                <CollectionEditBar row={row} busy={busy} onSetCount={onSetCount}
                  onRemove={onRemove} onPickPrinting={onPickPrinting} />
              )}
            </div>

            <div style={{ padding: '6px 8px 7px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minHeight: 24 }}>
                <CardHover name={row.name}
                  style={{ flex: '1 1 auto', minWidth: 0, fontSize: 12.5, color: c.text,
                           overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {row.name}
                </CardHover>
                <span style={{ flex: '0 0 auto' }}><ManaCost cost={row.mana_cost} size={13} /></span>
              </div>
              <div style={{ fontSize: 11, color: c.dim, overflow: 'hidden',
                            textOverflow: 'ellipsis', whiteSpace: 'nowrap', minHeight: 15 }}>
                {row.type_line || ''}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, marginTop: 2 }}>
                <SetChip set={row.set} cn={row.cn} rarity={row.rarity} setName={row.set_name}
                  mismatch={row.printing_mismatch} />
                {row.finish === 'foil' && <span style={{ color: c.faint }}>foil</span>}
                {row.finish === 'etched' && <span style={{ color: c.faint }}>etched</span>}
                <span style={{ marginLeft: 'auto', color: c.gold, fontWeight: 700 }}>x{row.count}</span>
                {typeof row.price === 'number' && (
                  <span style={{ color: c.green, fontWeight: 700 }}>${row.price.toFixed(2)}</span>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
