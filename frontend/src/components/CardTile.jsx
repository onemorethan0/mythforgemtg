import { useEffect, useState } from 'react'
import ManaCost from './ManaCost'

// ── Card tile ─────────────────────────────────────────────────────────────────
export default function CardTile({ card, jobId, selected, onSelect, regenStatus, refreshTs, hasVideo, videoTs, videoFmt, showMotion = true }) {
  const [hover, setHover] = useState(false)
  const [videoFailed, setVideoFailed] = useState(false)

  // Use cache-busting timestamp when the card was freshly regenerated
  const imgSrc = (card.has_render || refreshTs)
    ? `/api/deck/${jobId}/card-image/${card.render_key}${refreshTs ? `?t=${refreshTs}` : ''}`
    : card.scryfall_img || null

  const videoSrc = hasVideo
    ? `/api/deck/${jobId}/card-video/${card.render_key}${videoTs ? `?t=${videoTs}` : ''}`
    : null
  // A fresh/re-animated video clears any prior load failure.
  useEffect(() => { setVideoFailed(false) }, [videoSrc])
  const showVideo = showMotion && videoSrc && !videoFailed
  // WebP/GIF are animated images (render in <img>); MP4 needs a <video>.
  const fmt = videoFmt || card.video_meta?.format || 'mp4'
  const videoIsImage = fmt === 'webp' || fmt === 'gif'

  const selectable = onSelect != null

  return (
    <div
      className="deck-card-tile"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={selectable ? (e) => onSelect(card.render_key, e.shiftKey) : undefined}
      style={{
        position: 'relative', borderRadius: 8, overflow: 'hidden',
        cursor: selectable ? 'pointer' : 'default',
        aspectRatio: '480/672',
        outline:    selected ? '2px solid #eab308' : hover && selectable ? '2px solid #44403c' : '2px solid transparent',
        transform:  selected ? 'scale(1.03)' : 'scale(1)',
        transition: 'transform 0.12s, outline 0.12s',
        userSelect: 'none',
      }}
    >
      {showVideo
        ? (videoIsImage
          ? <img src={videoSrc} alt={card.themed_name}
                 onError={() => setVideoFailed(true)}
                 style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', background: '#000' }} />
          : <video src={videoSrc} poster={imgSrc || undefined}
                 autoPlay loop muted playsInline preload="auto" controls={hover}
                 onError={() => setVideoFailed(true)}
                 onLoadedData={e => { const p = e.currentTarget.play?.(); if (p && p.catch) p.catch(() => {}) }}
                 style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', background: '#000' }} />)
        : imgSrc
        ? <img src={imgSrc} alt={card.themed_name} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
        : (
          <div style={{ width: '100%', height: '100%', background: '#1c1917', border: '1px solid #292524', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 8, boxSizing: 'border-box' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#f5f5f4', textAlign: 'center', marginBottom: 4 }}>{card.themed_name}</div>
            <ManaCost cost={card.mana_cost} size={14} />
            <div style={{ fontSize: 9, color: '#78716c', marginTop: 4, textAlign: 'center' }}>{card.type_line}</div>
          </div>
        )
      }

      {/* Selection checkbox */}
      {selectable && (hover || selected) && (
        <div style={{
          position: 'absolute', top: 5, right: 5,
          width: 18, height: 18, borderRadius: '50%',
          background: selected ? '#eab308' : 'rgba(12,10,9,0.75)',
          border: `2px solid ${selected ? '#eab308' : '#78716c'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 10, fontWeight: 900, color: '#0c0a09',
        }}>
          {selected ? '✓' : ''}
        </div>
      )}

      {/* Regen-in-progress spinner */}
      {regenStatus === 'pending' && (
        <div style={{
          position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.72)',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6,
        }}>
          <div style={{ fontSize: 22, animation: 'spin-slow 1.5s linear infinite' }}>⚙️</div>
          <div style={{ fontSize: 9, color: '#eab308', fontWeight: 700 }}>Generating…</div>
        </div>
      )}

      {/* "NEW" badge after fresh regen */}
      {regenStatus === 'done' && (
        <div style={{
          position: 'absolute', top: 5, left: 5, fontSize: 9,
          padding: '2px 6px', borderRadius: 4, fontWeight: 700,
          background: '#14532d', color: '#86efac', border: '1px solid #166534',
        }}>
          NEW
        </div>
      )}

      {/* "UPGRADE" badge on advisor-applied swaps (unthemed: Scryfall art until regen) */}
      {card.swapped_in && regenStatus !== 'done' && (
        <div title="Added by the upgrade advisor — real card art until you regenerate it"
          style={{
            position: 'absolute', top: 5, left: 5, fontSize: 9,
            padding: '2px 6px', borderRadius: 4, fontWeight: 700,
            background: '#0c1a0c', color: '#4ade80', border: '1px solid #166534',
          }}>
          UPGRADE
        </div>
      )}

      {/* Ownership. EVERY card here has custom art, so the badge conveys whether you own
          a real copy — not "proxy" (which read as "you don't own this"). */}
      {card.owned === true && (
        <div title="Custom art for a card you own (in your collection)"
          style={{
            position: 'absolute', bottom: 5, left: 5, fontSize: 8.5,
            padding: '1px 5px', borderRadius: 4, fontWeight: 700, letterSpacing: '0.03em',
            background: '#0c1a0ccc', color: '#4ade80', border: '1px solid #166534',
          }}>
          ✓ OWNED
        </div>
      )}
      {card.owned === false && (
        <div title="You don't own a real copy of this card yet"
          style={{
            position: 'absolute', bottom: 5, left: 5, fontSize: 8.5,
            padding: '1px 5px', borderRadius: 4, fontWeight: 700, letterSpacing: '0.03em',
            background: '#1c1408cc', color: '#eab308', border: '1px solid #a16207',
          }}>
          NOT OWNED
        </div>
      )}

      {/* Animated indicator + download */}
      {videoSrc && regenStatus !== 'pending' && (
        <a href={videoSrc} download={`${card.render_key}.mp4`} title="Download MP4"
           onClick={e => e.stopPropagation()}
           style={{
             position: 'absolute', bottom: 5, left: 5, fontSize: 9,
             padding: '2px 6px', borderRadius: 4, fontWeight: 700, textDecoration: 'none',
             background: 'rgba(12,10,9,0.78)', color: '#a5b4fc', border: '1px solid #4f46e5',
             pointerEvents: hover ? 'auto' : 'none', opacity: hover ? 1 : 0.85,
           }}>
          ▶ MP4
        </a>
      )}

      {/* Hover overlay */}
      {!regenStatus || regenStatus !== 'pending' ? (
        <div className="deck-card-overlay" style={{
          position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.88)',
          padding: 10, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end',
          opacity: hover && !selected ? 1 : 0, transition: 'opacity 0.2s', overflow: 'hidden',
          pointerEvents: 'none',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#fde047', marginBottom: 2 }}>{card.themed_name}</div>
          {card.themed_name !== card.original_name && (
            <div style={{ fontSize: 9, color: '#78716c', marginBottom: 4 }}>({card.original_name})</div>
          )}
          {card.flavor_text && (
            <div style={{ fontSize: 9, color: '#d6d3d1', fontStyle: 'italic', lineHeight: 1.4, maxHeight: 36, overflow: 'hidden', marginBottom: 4 }}>{card.flavor_text}</div>
          )}
          {card.art_prompt && (
            <div style={{ fontSize: 8, color: '#a8a29e', lineHeight: 1.3, maxHeight: 40, overflow: 'hidden', borderTop: '1px solid #44403c', paddingTop: 4, marginTop: 2 }}>
              <span style={{ color: '#78716c', fontWeight: 700 }}>prompt: </span>{card.art_prompt}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
