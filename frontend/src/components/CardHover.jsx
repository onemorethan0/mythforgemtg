import { useState, useRef, useCallback } from 'react'

// Wrap a card NAME so hovering shows the card image (Scryfall, resolved by the
// backend /api/card-image and cached here so each name is fetched at most once).
//   <CardHover name="Sol Ring">Sol Ring</CardHover>
// The floating preview follows the cursor and clamps to the viewport.

const _cache = new Map()   // name -> {normal, art_crop} | 'none'

function fetchImage(name) {
  if (_cache.has(name)) return Promise.resolve(_cache.get(name))
  return fetch(`/api/card-image?name=${encodeURIComponent(name)}`)
    .then(r => (r.ok ? r.json() : null))
    .then(d => {
      const v = d && d.normal ? d : 'none'
      _cache.set(name, v)
      return v
    })
    .catch(() => { _cache.set(name, 'none'); return 'none' })
}

export default function CardHover({ name, children, style }) {
  const [img, setImg] = useState(null)     // {normal,...} once resolved
  const [pos, setPos] = useState(null)     // {x, y} cursor, null = hidden
  const hovering = useRef(false)

  const onEnter = useCallback(e => {
    hovering.current = true
    setPos({ x: e.clientX, y: e.clientY })
    fetchImage(name).then(v => {
      if (hovering.current && v !== 'none') setImg(v)
    })
  }, [name])

  const onMove = useCallback(e => {
    if (hovering.current) setPos({ x: e.clientX, y: e.clientY })
  }, [])

  const onLeave = useCallback(() => {
    hovering.current = false
    setPos(null)
    setImg(null)
  }, [])

  // Clamp the ~230x320 preview inside the viewport, offset from the cursor.
  const W = 230, H = 320, GAP = 16
  let px = 0, py = 0
  if (pos) {
    const vw = window.innerWidth, vh = window.innerHeight
    px = pos.x + GAP + W > vw ? pos.x - GAP - W : pos.x + GAP
    py = Math.min(Math.max(pos.y - H / 2, 8), vh - H - 8)
  }

  return (
    <span
      onMouseEnter={onEnter}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      style={{ cursor: 'help', ...style }}
    >
      {children}
      {pos && img && (
        <img
          src={img.normal}
          alt={name}
          style={{
            position: 'fixed', left: px, top: py, width: W, zIndex: 9999,
            borderRadius: 12, boxShadow: '0 8px 30px rgba(0,0,0,0.7)',
            pointerEvents: 'none', border: '1px solid #000',
          }}
        />
      )}
    </span>
  )
}
