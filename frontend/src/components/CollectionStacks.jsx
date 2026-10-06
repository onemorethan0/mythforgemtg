import { useState } from 'react'
import CardFace from './CardFace'
import CollectionEditBar from './CollectionEditBar'
import { TILE_SIZES, splitByGroup } from '../utils/collectionView'

// Stacks: one column per group in a horizontally scrolling row. Cards overlap so only the
// top STRIP of each (the name bar) shows; hovering one lifts it above its neighbours to
// full view. The scroller pads every side by more than the lift and the shadow reach, so
// a lifted card never clips at a column edge.
//
// Props: { cards, groups, size, onSetCount, onRemove, onPickPrinting,
//          selectMode?, selected?, onToggleSelect?, busy?, onShowAll? }

const STRIP = 0.14          // visible share of each card's height
const ASPECT = 1.4          // card height / width
const LIFT = 8              // px a hovered card rises
const PAD = 18              // scroller padding: > LIFT + shadow blur

const c = {
  gold:   '#eab308',
  green:  '#4ade80',
  dim:    '#a8a29e',
  faint:  '#78716c',
  amber:  '#fbbf24',
  card:   '#1c1917',
  border: '#292524',
  text:   '#f5f5f4',
}

export default function CollectionStacks({ cards, groups, size = 'm', onSetCount, onRemove,
                                           onPickPrinting, selectMode, selected, onToggleSelect,
                                           busy, onShowAll }) {
  const [hovered, setHovered] = useState(null)
  const sections = splitByGroup(cards, groups)
  const picked = selected || new Set()

  if (sections.length === 0) {
    return <div style={{ fontSize: 13, color: c.faint, padding: 20, textAlign: 'center' }}>
      Nothing to show.
    </div>
  }

  const w = TILE_SIZES[size] || TILE_SIZES.m
  const h = Math.round(w * ASPECT)
  const strip = Math.round(h * STRIP)

  return (
    <div style={{ overflowX: 'auto', padding: PAD, margin: -PAD, maxWidth: '100%',
                  boxSizing: 'content-box' }}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', width: 'max-content' }}>
        {sections.map(sec => {
          const rows = sec.pageRows
          return (
            <div key={sec.key} style={{ width: w, flex: '0 0 auto' }}>
              <div title={sec.label} style={{ fontSize: 12.5, marginBottom: 8, color: c.gold,
                                              fontWeight: 700, overflow: 'hidden',
                                              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {sec.headerless ? 'All cards' : sec.label}
                {!sec.headerless && <span style={{ color: c.dim, fontWeight: 400 }}> · {sec.cards}</span>}
              </div>
              <div style={{ position: 'relative', height: strip * (rows.length - 1) + h }}>
                {rows.map((row, i) => {
                  const key = row.row_id
                  const isSel = picked.has(key)
                  const isHot = hovered === key
                  const hasImg = !!(row.image_normal || row.image)
                  return (
                    <div key={key}
                      onMouseEnter={() => setHovered(key)}
                      onMouseLeave={() => setHovered(x => (x === key ? null : x))}
                      onClick={selectMode ? () => onToggleSelect && onToggleSelect(row) : undefined}
                      style={{ position: 'absolute', left: 0, top: i * strip, width: w, height: h,
                               borderRadius: 8, overflow: 'hidden', background: c.card,
                               cursor: selectMode ? 'pointer' : 'default',
                               border: `${isSel ? 2 : 1}px solid ${isSel ? c.gold : c.border}`,
                               boxSizing: 'border-box',
                               zIndex: isHot ? 1000 : i + 1,
                               transform: isHot ? `translateY(-${LIFT}px)` : 'none',
                               boxShadow: isHot ? '0 6px 14px rgba(0,0,0,0.7)' : 'none',
                               transition: 'transform 120ms ease, box-shadow 120ms ease' }}>
                      <CardFace row={row} />
                      {!hasImg && (
                        <div style={{ position: 'absolute', left: 0, right: 0, top: 0, height: strip,
                                      background: c.card, color: c.text, fontSize: 12, padding: '0 8px',
                                      display: 'flex', alignItems: 'center', boxSizing: 'border-box',
                                      overflow: 'hidden', whiteSpace: 'nowrap' }}>
                          {row.name}
                        </div>
                      )}
                      {row.count > 1 && !isHot && (
                        <span style={{ position: 'absolute', right: 4, top: strip - 17, padding: '0 5px',
                                       borderRadius: 5, fontSize: 10.5, fontWeight: 700, lineHeight: '14px',
                                       background: 'rgba(0,0,0,0.82)', color: c.gold }}>
                          x{row.count}
                        </span>
                      )}
                      {isHot && !selectMode && (
                        <CollectionEditBar row={row} busy={busy} onSetCount={onSetCount}
                          onRemove={onRemove} onPickPrinting={onPickPrinting} />
                      )}
                    </div>
                  )
                })}
              </div>
              {sec.continues && (
                <div style={{ fontSize: 11.5, color: c.amber, marginTop: 8 }}>
                  continues — {rows.length} of {sec.rows}
                  {onShowAll && (
                    <button onClick={onShowAll}
                      style={{ marginLeft: 6, background: 'none', border: `1px solid ${c.border}`,
                               borderRadius: 6, color: c.amber, cursor: 'pointer',
                               fontFamily: 'inherit', fontSize: 11.5, padding: '1px 6px' }}>
                      Show all
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
