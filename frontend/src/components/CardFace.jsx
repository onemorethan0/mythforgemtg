// One card face for one owned printing. Used by the binder grid, the printing picker and the
// deck view, so every surface shows the SAME exact printing the same way:
//   - foil rows get an animated sheen (CSS .mf-foil, off under prefers-reduced-motion)
//   - etched rows get an ETCHED badge
//   - a row whose printing is unknown shows the oracle-index art with a corner "≈"
//   - a double-faced card gets a flip button that swaps to the back face
// The component fills its parent (width/height 100%); the caller owns size and aspect ratio.
// `flipped` / `onFlip` are controlled so the caller keeps flip state per tile.

import { dotColor } from '../utils/collectionView'

const c = {
  gold:   '#eab308',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
  dim:    '#a8a29e',
  faint:  '#78716c',
}

const RARITY_COLOR = {
  common: '#a8a29e', uncommon: '#cbd5e1', rare: '#eab308', mythic: '#f97316',
  special: '#c084fc', bonus: '#c084fc',
}

const marker = extra => ({
  padding: '1px 6px', borderRadius: 6, fontSize: 10.5, fontWeight: 700, lineHeight: '15px',
  background: 'rgba(0,0,0,0.82)', border: `1px solid ${c.border}`, ...extra,
})

// The set code, coloured by rarity. Props beyond {set, cn, rarity} are optional extras.
export function SetChip({ set, cn, rarity, setName, mismatch, style }) {
  if (!set) return null
  const color = RARITY_COLOR[String(rarity || '').toLowerCase()] || c.faint
  let title = `${setName || String(set).toUpperCase()}${cn ? ` #${cn}` : ''}`
  if (mismatch) title += ' — Scryfall ID points to this printing'
  return (
    <span title={title}
      style={{ color, fontWeight: 700, fontSize: 10, letterSpacing: 0.3, ...style }}>
      {String(set).toUpperCase()}{mismatch ? '*' : ''}
    </span>
  )
}

export default function CardFace({ row, variant = 'full', flipped = false, onFlip }) {
  const r = row || {}
  const art = variant === 'art'
  const hasBack = !!r.back_image && !art
  const showBack = hasBack && flipped

  // Fall back gracefully: full -> image_normal -> image; art -> art_crop -> the full image
  // cropped to cover.
  const fullSrc = r.image_normal || r.image || null
  const src = showBack ? r.back_image : (art ? (r.art_crop || fullSrc) : fullSrc)
  const foil = r.finish === 'foil'
  const etched = r.finish === 'etched'

  return (
    <div className={foil ? 'mf-foil' : undefined}
      style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden',
               background: c.card }}>
      {src ? (
        <img src={src} alt={r.name || ''} loading="lazy"
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
      ) : (
        <div style={{ width: '100%', height: '100%', background: c.panel, padding: 8,
                      boxSizing: 'border-box', display: 'flex', flexDirection: 'column',
                      alignItems: 'center', justifyContent: 'center', gap: 6,
                      textAlign: 'center', overflow: 'hidden' }}>
          <span style={{ width: 14, height: 14, borderRadius: '50%',
                         background: dotColor(r) || 'transparent',
                         border: dotColor(r) ? 'none' : `1px solid ${c.faint}` }} />
          <span style={{ fontSize: 11.5, color: c.dim }}>{r.name}</span>
          {r.type && <span style={{ fontSize: 10, color: c.faint }}>{r.type}</span>}
        </div>
      )}

      {/* Bottom-right marker cluster. The count/price badges own the top corners and the
          Game Changer badge owns bottom-left, so these never collide with them. */}
      {(etched || (r.image_representative && src)) && (
        <div style={{ position: 'absolute', right: 6, bottom: 6, display: 'flex', gap: 4,
                      zIndex: 2 }}>
          {etched && <span style={marker({ color: '#67e8f9', borderColor: '#0e7490' })}>ETCHED</span>}
          {r.image_representative && src && (
            <span title="Printing unknown — showing a representative printing"
              style={marker({ color: c.dim })}>≈</span>
          )}
        </div>
      )}

      {hasBack && (
        <button type="button"
          title={showBack ? 'Show front face' : 'Show back face'}
          onClick={e => { e.stopPropagation(); onFlip && onFlip() }}
          style={{ ...marker({ color: c.gold, cursor: 'pointer', fontFamily: 'inherit',
                               fontSize: 13, padding: '0 6px' }),
                   position: 'absolute', right: 6, top: 30, zIndex: 2 }}>↻</button>
      )}
    </div>
  )
}
