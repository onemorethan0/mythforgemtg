import { useEffect, useRef, useState } from 'react'
import ManaCost from './ManaCost'

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const TYPE_ORDER = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Planeswalker', 'Land']

function groupByType(cards) {
  const groups = {}
  for (const type of TYPE_ORDER) groups[type] = []
  groups['Other'] = []
  for (const c of cards) {
    const tl = c.type_line || ''
    let placed = false
    for (const type of TYPE_ORDER) {
      if (tl.includes(type)) { groups[type].push(c); placed = true; break }
    }
    if (!placed) groups['Other'].push(c)
  }
  return groups
}

function triggerDownload(url) {
  const a = document.createElement('a'); a.href = url; a.click()
}

function exportMoxfield(deck) {
  const lines = deck.deck.map(c => `1 ${c.original_name}`)
  lines.unshift(`1 ${deck.commander.original_name}`)
  const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
  a.download = `${deck.commander.original_name.replace(/[^a-z0-9]/gi, '_')}_deck.txt`; a.click()
}

function exportThemed(deck) {
  const lines = [`Commander: ${deck.commander.themed_name} (${deck.commander.original_name})`, '']
  const groups = groupByType(deck.deck)
  for (const type of [...TYPE_ORDER, 'Other']) {
    if (!groups[type]?.length) continue
    lines.push(`// ${type} (${groups[type].length})`)
    groups[type].forEach(c => lines.push(`1 ${c.themed_name} (${c.original_name})`))
    lines.push('')
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
  a.download = `${deck.commander.themed_name.replace(/[^a-z0-9]/gi, '_')}_themed.txt`; a.click()
}

async function triggerRetheme(jobId) {
  const res = await fetch(`/api/deck/${jobId}/retheme`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) throw new Error(`Retheme failed: ${res.status}`)
  return (await res.json()).job_id
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function StatBar({ label, value, max, color }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: '#a8a29e' }}>{label}</span>
        <span style={{ fontSize: 12, color: '#f5f5f4', fontWeight: 700 }}>{value}</span>
      </div>
      <div style={{ height: 4, background: '#292524', borderRadius: 2 }}>
        <div style={{ height: 4, background: color, borderRadius: 2, width: `${Math.min(100, (value / max) * 100)}%`, transition: 'width 0.5s' }} />
      </div>
    </div>
  )
}

function CmcChart({ curve }) {
  if (!curve) return null
  const entries = Object.entries(curve).sort((a, b) => Number(a[0]) - Number(b[0]))
  const maxVal = Math.max(...entries.map(([, v]) => v), 1)
  return (
    <div>
      <div style={{ fontSize: 12, color: '#78716c', marginBottom: 8 }}>Mana Curve</div>
      <div style={{ display: 'flex', gap: 4, alignItems: 'flex-end', height: 60 }}>
        {entries.map(([cmc, count]) => (
          <div key={cmc} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
            <div style={{ width: '100%', background: '#ca8a04', borderRadius: '3px 3px 0 0', height: `${(count / maxVal) * 52}px`, minHeight: count > 0 ? 4 : 0 }} />
            <span style={{ fontSize: 10, color: '#78716c' }}>{cmc === '7' ? '7+' : cmc}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Card tile ─────────────────────────────────────────────────────────────────
function CardTile({ card, jobId, selected, onSelect, regenStatus, refreshTs, hasVideo, videoTs, videoFmt, showMotion = true }) {
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
      onClick={selectable ? () => onSelect(card.render_key) : undefined}
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

// ── Regen panel (modal) ────────────────────────────────────────────────────────
function RegenPanel({ selectedCards, onStart, onClose, defaultArtStyle, defaultModelSpeed,
                      defaultCheckpoint,
                      commanderOriginalName, savedFaceKey, savedFaceGender,
                      savedCrewKey, savedCrewGender }) {
  // Per-card prompt state. The LLM art_prompt is immutable; customPrompts holds the
  // user's separate override text, and useCustom decides which one feeds generation.
  const [customPrompts, setCustomPrompts] = useState(
    () => Object.fromEntries(selectedCards.map(c => [c.render_key, c.custom_prompt ?? ''])))
  const [useCustom, setUseCustom] = useState(
    () => Object.fromEntries(selectedCards.map(c => [c.render_key, !!c.use_custom])))
  const [artStyle, setArtStyle]           = useState(defaultArtStyle || 'mtg_fantasy')
  const [modelSpeed, setModelSpeed]       = useState(defaultModelSpeed || 'quality')
  const [checkpoint, setCheckpoint]       = useState(defaultCheckpoint || null)
  const [artStyles, setArtStyles]         = useState([])
  const [ckpts, setCkpts]                 = useState([])

  // Fetch available art styles and checkpoints from API on mount
  useEffect(() => {
    fetch('/api/art-styles')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setArtStyles(d) })
      .catch(() => {})
    fetch('/api/checkpoints')
      .then(r => r.ok ? r.json() : [])
      .then(d => setCkpts(Array.isArray(d) ? d : []))
      .catch(() => {})
  }, [])

  const commanderSelected = selectedCards.some(c => c.original_name === commanderOriginalName)
  const creaturesSelected = selectedCards.some(c => c.original_name !== commanderOriginalName)

  // Commander face: 'saved' | 'upload' | 'none'
  const [faceMode, setFaceMode]               = useState(savedFaceKey ? 'saved' : 'none')
  const [uploadedFaceKey, setUploadedFaceKey] = useState(null)
  const [faceUploading, setFaceUploading]     = useState(false)
  const [faceUploadErr, setFaceUploadErr]     = useState(null)
  const faceInputRef                          = useRef(null)

  // Crew photos: 'saved' | 'upload' | 'none'
  const [crewMode, setCrewMode]               = useState(savedCrewKey ? 'saved' : 'none')
  const [uploadedCrewKey, setUploadedCrewKey] = useState(null)
  const [crewUploading, setCrewUploading]     = useState(false)
  const [crewUploadErr, setCrewUploadErr]     = useState(null)
  const crewInputRef                          = useRef(null)

  // Force a single uploaded face onto EVERY selected card, whatever its type.
  // This is the "add a friendly face to this card" path — it overrides the
  // commander/crew routing on the backend.
  const [forceFaceKey, setForceFaceKey]           = useState(null)
  const [forceFaceUploading, setForceFaceUploading] = useState(false)
  const [forceFaceErr, setForceFaceErr]           = useState(null)
  const [forceFaceGender, setForceFaceGender]     = useState('either')
  const forceFaceInputRef                         = useRef(null)

  function setPrompt(key, val) { setCustomPrompts(p => ({ ...p, [key]: val })) }
  // Enabling custom RECALLS the current prompt into the editable box (saved custom
  // if any, else the AI prompt) so you can tweak it instead of retyping. The AI
  // art_prompt itself is never modified — this only fills the separate custom field.
  function recallInto(prev, card) {
    const cur = prev[card.render_key]
    if (cur && cur.trim()) return prev
    return { ...prev, [card.render_key]: card.custom_prompt || card.art_prompt || '' }
  }
  function toggleCustom(card, val) {
    setUseCustom(m => ({ ...m, [card.render_key]: val }))
    if (val) setCustomPrompts(p => recallInto(p, card))
  }
  function setAllCustom(val) {
    setUseCustom(Object.fromEntries(selectedCards.map(c => [c.render_key, val])))
    if (val) setCustomPrompts(p => selectedCards.reduce((acc, c) => recallInto(acc, c), { ...p }))
  }

  async function handlePhotoUpload(e, setKey, setMode, setUploading, setErr) {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setUploading(true); setErr(null)
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f))
      let res
      try {
        res = await fetch('/api/upload-face', { method: 'POST', body: fd })
      } catch (netErr) {
        throw new Error(`Could not reach server: ${netErr.message}`)
      }
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const e = await res.json(); if (e.detail) detail = e.detail } catch {}
        throw new Error(detail)
      }
      const data = await res.json()
      setKey(data.face_key)
      setMode('upload')
    } catch (err) { setErr(err.message) }
    finally { setUploading(false) }
  }

  function handleStart() {
    let face_key = null
    if (commanderSelected) {
      if (faceMode === 'saved')  face_key = savedFaceKey    || null
      if (faceMode === 'upload') face_key = uploadedFaceKey || null
    }
    let crew_key = null
    if (creaturesSelected) {
      if (crewMode === 'saved')  crew_key = savedCrewKey    || null
      if (crewMode === 'upload') crew_key = uploadedCrewKey || null
    }
    onStart({
      cards: selectedCards.map(c => ({
        render_key:    c.render_key,
        original_name: c.original_name,
        custom_prompt: customPrompts[c.render_key] ?? '',
        use_custom:    !!useCustom[c.render_key],
      })),
      art_style:   artStyle,
      model_speed: modelSpeed,
      checkpoint:  checkpoint || null,
      face_key,
      face_gender: savedFaceGender || 'either',
      crew_key,
      crew_gender: savedCrewGender || 'either',
      force_face_key:    forceFaceKey || null,
      force_face_gender: forceFaceGender,
    })
  }

  const btnBase = { padding: '6px 16px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer', fontWeight: 600, border: 'none' }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 200, padding: 16,
    }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#1c1917', border: '1px solid #44403c', borderRadius: 16,
        width: '100%', maxWidth: 680, maxHeight: '85vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 22px 14px', borderBottom: '1px solid #292524', flexShrink: 0 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, color: '#fde047', fontWeight: 700 }}>
              🎲 Regenerate {selectedCards.length} Card{selectedCards.length !== 1 ? 's' : ''}
            </h3>
            <div style={{ fontSize: 12, color: '#78716c', marginTop: 3 }}>
              New random seeds — different art every time
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#78716c', fontSize: 18, cursor: 'pointer', padding: 4 }}>✕</button>
        </div>

        {/* Prompt source — per card below; these set all at once */}
        <div style={{ padding: '14px 22px 0', flexShrink: 0 }}>
          <div style={{ fontSize: 11, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>
            Prompt source <span style={{ textTransform: 'none', letterSpacing: 0, color: '#57534e' }}>— set all, or choose per card below</span>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {[
              { val: false, label: '📋 All: AI prompts', desc: 'Use the original AI-crafted prompt for every selected card' },
              { val: true,  label: '✏️ All: custom',     desc: 'Use the custom prompt for every selected card' },
            ].map(opt => (
              <button
                key={String(opt.val)}
                onClick={() => setAllCustom(opt.val)}
                title={opt.desc}
                style={{
                  ...btnBase,
                  padding: '7px 16px', fontWeight: 600,
                  background: '#0c0a09',
                  color:      '#a8a29e',
                  border:     '1px solid #292524',
                }}
              >{opt.label}</button>
            ))}
          </div>
        </div>

        {/* Force a friendly face onto the selected card(s) — any type */}
        <div style={{ padding: '14px 22px 0', flexShrink: 0 }}>
          <div style={{ fontSize: 11, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
            🙂 Add a face to {selectedCards.length === 1 ? 'this card' : 'these cards'}
            <span style={{ textTransform: 'none', letterSpacing: 0, color: '#57534e' }}> — applied to every selected card, even non-creatures</span>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <button onClick={() => forceFaceInputRef.current?.click()}
              disabled={forceFaceUploading}
              style={{ ...btnBase, padding: '6px 12px', fontSize: 11, opacity: forceFaceUploading ? 0.6 : 1,
                fontWeight: forceFaceKey ? 700 : 600,
                background: forceFaceKey ? '#1c3a22' : '#0c0a09',
                color:      forceFaceKey ? '#86efac' : '#a8a29e',
                border:     `1px solid ${forceFaceKey ? '#15803d' : '#44403c'}`,
              }}>
              {forceFaceUploading ? '⏳ Uploading…' : forceFaceKey ? '✓ Face loaded' : '↑ Upload a photo'}
            </button>
            {forceFaceKey && (
              <button onClick={() => { setForceFaceKey(null); setForceFaceErr(null) }}
                style={{ ...btnBase, padding: '6px 12px', fontSize: 11, fontWeight: 400,
                  background: '#0c0a09', color: '#57534e', border: '1px solid #292524' }}>✕ Clear</button>
            )}
            <label style={{ fontSize: 11, color: '#78716c', display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
              Look
              <select value={forceFaceGender} onChange={e => setForceFaceGender(e.target.value)}
                style={{ background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: 'inherit' }}>
                <option value="either">Either</option>
                <option value="male">Masc</option>
                <option value="female">Femme</option>
              </select>
            </label>
          </div>
          {forceFaceErr && <div style={{ fontSize: 10, color: '#f87171', marginTop: 4 }}>{forceFaceErr}</div>}
          {forceFaceKey && (
            <div style={{ fontSize: 10, color: '#65a30d', marginTop: 5 }}>
              This face will be used on {selectedCards.length === 1 ? 'the selected card' : `all ${selectedCards.length} selected cards`} — it overrides the commander/crew faces below.
            </div>
          )}
          <input ref={forceFaceInputRef} type="file" accept="image/*" multiple style={{ display: 'none' }}
            onChange={e => handlePhotoUpload(e, setForceFaceKey, () => {}, setForceFaceUploading, setForceFaceErr)} />
        </div>

        {/* Face/crew reference sections */}
        {(commanderSelected || creaturesSelected) && (
          <div style={{ padding: '12px 22px 0', flexShrink: 0, borderTop: '1px solid #1c1917', display: 'flex', gap: 12, flexWrap: 'wrap' }}>

            {/* Commander face */}
            {commanderSelected && (
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 10, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>👑 Commander face</div>
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {savedFaceKey && (
                    <button onClick={() => setFaceMode('saved')} style={{ ...btnBase, padding: '5px 10px', fontSize: 11,
                      fontWeight: faceMode === 'saved' ? 700 : 400,
                      background: faceMode === 'saved' ? '#1c3a22' : '#0c0a09',
                      color:      faceMode === 'saved' ? '#86efac' : '#78716c',
                      border:     `1px solid ${faceMode === 'saved' ? '#15803d' : '#292524'}`,
                    }}>✓ Saved</button>
                  )}
                  <button onClick={() => { setFaceMode('upload'); faceInputRef.current?.click() }}
                    disabled={faceUploading}
                    style={{ ...btnBase, padding: '5px 10px', fontSize: 11, opacity: faceUploading ? 0.6 : 1,
                      fontWeight: faceMode === 'upload' ? 700 : 400,
                      background: faceMode === 'upload' ? '#1c3a22' : '#0c0a09',
                      color:      faceMode === 'upload' ? '#86efac' : '#78716c',
                      border:     `1px solid ${faceMode === 'upload' ? '#15803d' : '#292524'}`,
                    }}>
                    {faceUploading ? '⏳' : uploadedFaceKey && faceMode === 'upload' ? '✓ Loaded' : '↑ Upload'}
                  </button>
                  <button onClick={() => setFaceMode('none')} style={{ ...btnBase, padding: '5px 10px', fontSize: 11,
                    fontWeight: faceMode === 'none' ? 700 : 400,
                    background: faceMode === 'none' ? '#292524' : '#0c0a09',
                    color:      faceMode === 'none' ? '#a8a29e' : '#57534e',
                    border:     `1px solid ${faceMode === 'none' ? '#44403c' : '#292524'}`,
                  }}>✕ None</button>
                </div>
                {faceUploadErr && <div style={{ fontSize: 10, color: '#f87171', marginTop: 4 }}>{faceUploadErr}</div>}
                <input ref={faceInputRef} type="file" accept="image/*" multiple style={{ display: 'none' }}
                  onChange={e => handlePhotoUpload(e, setUploadedFaceKey, setFaceMode, setFaceUploading, setFaceUploadErr)} />
              </div>
            )}

            {/* Crew photos */}
            {creaturesSelected && (
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 10, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>👥 Crew photos (creatures)</div>
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  {savedCrewKey && (
                    <button onClick={() => setCrewMode('saved')} style={{ ...btnBase, padding: '5px 10px', fontSize: 11,
                      fontWeight: crewMode === 'saved' ? 700 : 400,
                      background: crewMode === 'saved' ? '#1c3a22' : '#0c0a09',
                      color:      crewMode === 'saved' ? '#86efac' : '#78716c',
                      border:     `1px solid ${crewMode === 'saved' ? '#15803d' : '#292524'}`,
                    }}>✓ Saved</button>
                  )}
                  <button onClick={() => { setCrewMode('upload'); crewInputRef.current?.click() }}
                    disabled={crewUploading}
                    style={{ ...btnBase, padding: '5px 10px', fontSize: 11, opacity: crewUploading ? 0.6 : 1,
                      fontWeight: crewMode === 'upload' ? 700 : 400,
                      background: crewMode === 'upload' ? '#1c3a22' : '#0c0a09',
                      color:      crewMode === 'upload' ? '#86efac' : '#78716c',
                      border:     `1px solid ${crewMode === 'upload' ? '#15803d' : '#292524'}`,
                    }}>
                    {crewUploading ? '⏳' : uploadedCrewKey && crewMode === 'upload' ? '✓ Loaded' : '↑ Upload'}
                  </button>
                  <button onClick={() => setCrewMode('none')} style={{ ...btnBase, padding: '5px 10px', fontSize: 11,
                    fontWeight: crewMode === 'none' ? 700 : 400,
                    background: crewMode === 'none' ? '#292524' : '#0c0a09',
                    color:      crewMode === 'none' ? '#a8a29e' : '#57534e',
                    border:     `1px solid ${crewMode === 'none' ? '#44403c' : '#292524'}`,
                  }}>✕ None</button>
                </div>
                {crewUploadErr && <div style={{ fontSize: 10, color: '#f87171', marginTop: 4 }}>{crewUploadErr}</div>}
                <input ref={crewInputRef} type="file" accept="image/*" multiple style={{ display: 'none' }}
                  onChange={e => handlePhotoUpload(e, setUploadedCrewKey, setCrewMode, setCrewUploading, setCrewUploadErr)} />
              </div>
            )}
          </div>
        )}

        {/* Card list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 22px', minHeight: 0 }}>
          {selectedCards.map(card => (
            <div key={card.render_key} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: '1px solid #292524' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 5 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#fde047' }}>{card.themed_name}</span>
                {card.themed_name !== card.original_name && (
                  <span style={{ fontSize: 10, color: '#57534e' }}>({card.original_name})</span>
                )}
              </div>
              {/* AI (LLM) prompt — always shown, never edited/overwritten */}
              <div style={{ fontSize: 9, color: '#57534e', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>AI prompt</div>
              <div style={{
                fontSize: 10, color: useCustom[card.render_key] ? '#44403c' : '#a8a29e',
                lineHeight: 1.5, fontStyle: card.art_prompt ? 'normal' : 'italic',
                textDecoration: useCustom[card.render_key] ? 'line-through' : 'none',
              }}>
                {card.art_prompt || '(no saved prompt — will fall back to card name)'}
              </div>

              {/* Per-card choice: use a separate custom prompt instead */}
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '7px 0 0', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={!!useCustom[card.render_key]}
                  onChange={e => toggleCustom(card, e.target.checked)}
                  style={{ accentColor: '#eab308' }}
                />
                <span style={{ fontSize: 11, color: useCustom[card.render_key] ? '#fde047' : '#78716c' }}>
                  Use a custom prompt for this card
                </span>
              </label>

              {useCustom[card.render_key] && (
                <>
                  <textarea
                    value={customPrompts[card.render_key] ?? ''}
                    onChange={e => setPrompt(card.render_key, e.target.value)}
                    placeholder="Describe the art for this card…"
                    rows={3}
                    style={{
                      width: '100%', boxSizing: 'border-box', marginTop: 6,
                      background: '#0c0a09', color: '#f5f5f4',
                      border: '1px solid #44403c', borderRadius: 6,
                      padding: '7px 10px', fontSize: 11, lineHeight: 1.5,
                      resize: 'vertical', fontFamily: 'inherit', outline: 'none',
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setPrompt(card.render_key, card.art_prompt || '')}
                    title="Reload the AI prompt into the box so you can edit from it"
                    style={{ marginTop: 4, fontSize: 10, color: '#78716c', background: 'none',
                             border: '1px solid #292524', borderRadius: 5, padding: '3px 8px',
                             cursor: 'pointer', fontFamily: 'inherit' }}
                  >↺ Reset to AI prompt</button>
                </>
              )}
            </div>
          ))}
        </div>

        {/* Settings row */}
        <div style={{ padding: '10px 22px', borderTop: '1px solid #292524', flexShrink: 0, display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 11, color: '#78716c', display: 'flex', alignItems: 'center', gap: 6 }}>
            Art style
            <select
              value={artStyle}
              onChange={e => setArtStyle(e.target.value)}
              style={{ background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: 'inherit' }}
            >
              {artStyles.length > 0 ? (
                artStyles.map(s => (
                  <option key={s.key} value={s.key} disabled={!s.ready && !s.partial}>
                    {s.icon} {s.label}{s.ready ? '' : s.partial ? ' (partial)' : ' (missing)'}
                  </option>
                ))
              ) : (
                <option value="mtg_fantasy">MTG Fantasy</option>
              )}
            </select>
          </label>
          {/* Model picker */}
          {ckpts.length > 0 ? (() => {
            const activeCkpt   = ckpts.find(c => c.filename === checkpoint)
            const activeType   = (activeCkpt?.type || '').toUpperCase()
            const isSchnellAct = checkpoint?.toLowerCase().includes('schnell')
            const isDevAct     = activeType.includes('FLUX') && !isSchnellAct
            const isSDXLAct    = activeType.includes('SDXL')
            const isSd35Act    = activeType.includes('SD') && !isSDXLAct && !activeType.includes('FLUX')
            const hasDev_   = ckpts.some(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))
            const hasSch_   = ckpts.some(c => c.filename.toLowerCase().includes('schnell'))
            const hasSDXL_  = ckpts.some(c => (c.type||'').toUpperCase().includes('SDXL'))
            const hasSd35_  = ckpts.some(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') && !t.includes('FLUX') })
            const pick = (fn, speed) => { setCheckpoint(fn); if (speed) setModelSpeed(speed) }
            return (
              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {hasDev_ && (
                  <button onClick={() => pick(ckpts.find(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))?.filename, 'quality')}
                    style={{ ...btnBase, padding: '5px 10px', fontSize: 11, fontWeight: isDevAct ? 700 : 400,
                      background: isDevAct ? '#1c1410' : '#0c0a09', color: isDevAct ? '#eab308' : '#78716c',
                      border: `1px solid ${isDevAct ? '#ca8a04' : '#292524'}` }}>✦ Quality</button>
                )}
                {hasSDXL_ && (
                  <button onClick={() => pick(ckpts.find(c => (c.type||'').toUpperCase().includes('SDXL'))?.filename, null)}
                    style={{ ...btnBase, padding: '5px 10px', fontSize: 11, fontWeight: isSDXLAct ? 700 : 400,
                      background: isSDXLAct ? '#120a1e' : '#0c0a09', color: isSDXLAct ? '#a78bfa' : '#78716c',
                      border: `1px solid ${isSDXLAct ? '#a78bfa' : '#292524'}` }}>🎨 Illustrious</button>
                )}
                {hasSd35_ && (
                  <button onClick={() => pick(ckpts.find(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') && !t.includes('FLUX') })?.filename, 'sd35')}
                    style={{ ...btnBase, padding: '5px 10px', fontSize: 11, fontWeight: isSd35Act ? 700 : 400,
                      background: isSd35Act ? '#100a18' : '#0c0a09', color: isSd35Act ? '#818cf8' : '#78716c',
                      border: `1px solid ${isSd35Act ? '#818cf8' : '#292524'}` }}>✧ SD 3.5</button>
                )}
                {hasSch_ && (
                  <button onClick={() => pick(ckpts.find(c => c.filename.toLowerCase().includes('schnell'))?.filename, 'fast')}
                    style={{ ...btnBase, padding: '5px 10px', fontSize: 11, fontWeight: isSchnellAct ? 700 : 400,
                      background: isSchnellAct ? '#0a1008' : '#0c0a09', color: isSchnellAct ? '#4ade80' : '#78716c',
                      border: `1px solid ${isSchnellAct ? '#4ade80' : '#292524'}` }}>⚡ Fast</button>
                )}
              </div>
            )
          })() : (
            <label style={{ fontSize: 11, color: '#78716c', display: 'flex', alignItems: 'center', gap: 6 }}>
              Speed
              <select value={modelSpeed} onChange={e => setModelSpeed(e.target.value)}
                style={{ background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '4px 8px', fontSize: 11, fontFamily: 'inherit' }}>
                <option value="quality">Quality (FLUX dev)</option>
                <option value="fast">Fast (FLUX schnell)</option>
              </select>
            </label>
          )}
        </div>

        {/* Actions */}
        <div style={{ padding: '12px 22px 18px', borderTop: '1px solid #292524', flexShrink: 0, display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ ...btnBase, background: '#292524', color: '#a8a29e', border: '1px solid #44403c', fontWeight: 400 }}>
            Cancel
          </button>
          <button onClick={handleStart} style={{ ...btnBase, background: '#3b0764', color: '#c4b5fd', border: '1px solid #7c3aed' }}>
            🎲 Generate New Images
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Animate panel (modal) ───────────────────────────────────────────────────
function AnimatePanel({ selectedCards, presets, foilStyles, formats, loopStyles, caps, health, onStart, onClose }) {
  const i2vOk = !!health?.ok
  const [effect, setEffect]   = useState(i2vOk ? 'motion' : 'foil')
  const [preset, setPreset]   = useState(presets?.[0]?.key || 'subtle')
  const [foilStyle, setFoilStyle] = useState(foilStyles?.[0]?.key || 'holo')
  const [fmt, setFmt]         = useState('mp4')
  const [loop, setLoop]       = useState(true)
  const [loopStyle, setLoopStyle] = useState('crossfade')

  const usesMotion = effect === 'motion' || effect === 'motion_foil'
  const usesFoil   = effect === 'foil'   || effect === 'motion_foil'
  const canRun     = !usesMotion || i2vOk

  // ── Clip length (duration) + frame rate + foil intensity ──
  const FALLBACK_CAPS = { motion: { min_s: 1, max_s: 6, default_s: 2 },
                          foil: { min_s: 1, max_s: 10, default_s: 3 }, fps_options: [12, 16, 24, 30] }
  const capsR     = caps || FALLBACK_CAPS
  const fpsOptions = capsR.fps_options || FALLBACK_CAPS.fps_options
  // Motion clip-length range applies whenever I2V runs (motion or motion_foil);
  // foil-only uses the cheaper, longer foil range.
  const range     = usesMotion ? (capsR.motion || FALLBACK_CAPS.motion) : (capsR.foil || FALLBACK_CAPS.foil)
  const [duration, setDuration] = useState(range.default_s)
  const [fps, setFps]           = useState(24)
  const [foilIntensity, setFoilIntensity] = useState(0.55)
  const [customMotion, setCustomMotion]   = useState('')   // free-text when preset === '__custom__'
  const isCustomMotion = preset === '__custom__'
  const [motionStrength, setMotionStrength] = useState(capsR.motion_strength_default ?? 0.5)

  // Keep duration within the active effect's range when the effect switches.
  useEffect(() => {
    setDuration(d => Math.min(range.max_s, Math.max(range.min_s, d)))
  }, [effect])  // eslint-disable-line react-hooks/exhaustive-deps

  const clampedDur = Math.min(range.max_s, Math.max(range.min_s, duration))
  const estFrames  = Math.max(2, Math.round(clampedDur * fps))
  // Bounce (ping-pong) plays ~2× on screen; crossfade is forward-only (~1×, minus
  // the dissolve); foil already loops once.
  const loopMult   = (usesMotion && !usesFoil && loopStyle === 'bounce') ? 2 : 1
  const onScreenS  = (clampedDur * loopMult).toFixed(1)

  function handleStart() {
    onStart({
      cards: selectedCards.map(c => ({ render_key: c.render_key, original_name: c.original_name })),
      motion_preset: isCustomMotion ? 'subtle' : preset,
      motion_prompt: isCustomMotion ? customMotion.trim() : undefined,
      motion_strength: motionStrength,
      effect,
      foil_style: foilStyle,
      foil_intensity: foilIntensity,
      fmt,
      duration: clampedDur,
      fps,
      loop_style: loopStyle,
      loop: loopStyle !== 'off',
    })
  }

  const modelLabel = health?.method
    ? health.method.toUpperCase()
    : (health?.methods?.length ? health.methods.join(', ') : 'auto')

  // Local button style (this component is top-level — it can't see StepDeck's btnBase).
  const btnBase = { padding: '6px 16px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer', fontWeight: 600, border: 'none' }
  const selStyle = { width: '100%', padding: '8px 10px', background: '#0c0a09', color: '#f5f5f4',
    border: '1px solid #44403c', borderRadius: 8, fontSize: 13, marginBottom: 14 }

  const effectOptions = [
    { key: 'motion', label: '🎞️ Art motion (image-to-video)', needsI2v: true },
    { key: 'foil',   label: '✨ Foil / holo sheen (whole card)', needsI2v: false },
    { key: 'motion_foil', label: '🎞️+✨ Motion + foil', needsI2v: true },
  ]
  const fmtList   = formats?.length ? formats
    : [{ key: 'mp4', label: 'MP4 (H.264 video)' }, { key: 'webp', label: 'Animated WebP' }, { key: 'gif', label: 'Animated GIF' }]
  const foilList  = foilStyles?.length ? foilStyles
    : [{ key: 'holo', label: 'Rainbow holo' }, { key: 'gold', label: 'Gold foil' }, { key: 'silver', label: 'Silver shimmer' }]

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: 16 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{ background: '#1c1917', border: '1px solid #44403c', borderRadius: 16,
        maxWidth: 560, width: '100%', maxHeight: '88vh', overflowY: 'auto', padding: 24 }}>
        <div style={{ fontSize: 18, fontWeight: 800, color: '#7dd3fc', marginBottom: 4 }}>
          ✨ Animate {selectedCards.length} card{selectedCards.length !== 1 ? 's' : ''}
        </div>
        <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 16 }}>
          {usesFoil && !usesMotion
            ? 'A holographic foil sheen sweeps across the whole card — frame, text and art. Runs on CPU, no GPU model needed (~seconds per card).'
            : `The card art is turned into a short looping clip (${modelLabel}); the frame, text and symbols stay crisp. This runs on your GPU and takes ~½–2 min per card.`}
        </div>

        {/* Effect */}
        <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Effect</label>
        <select value={effect} onChange={e => setEffect(e.target.value)} style={selStyle}>
          {effectOptions.map(o => (
            <option key={o.key} value={o.key} disabled={o.needsI2v && !i2vOk}>
              {o.label}{o.needsI2v && !i2vOk ? ' — needs a video model' : ''}
            </option>
          ))}
        </select>

        {/* Motion preset (only when art motion is used) */}
        {usesMotion && (<>
          <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Motion</label>
          <select value={preset} onChange={e => setPreset(e.target.value)} style={{ ...selStyle, marginBottom: isCustomMotion ? 8 : 14 }}>
            {(presets?.length ? presets : [{ key: 'subtle', label: 'Subtle cinemagraph' }]).map(p => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
            <option value="__custom__">✍️ Custom motion…</option>
          </select>
          {isCustomMotion && (<>
            <textarea
              value={customMotion}
              onChange={e => setCustomMotion(e.target.value)}
              maxLength={300}
              rows={2}
              placeholder="e.g. slow camera push-in, rain falling, neon signs flickering"
              style={{ ...selStyle, marginBottom: 4, resize: 'vertical', minHeight: 44 }}
            />
            <div style={{ fontSize: 11, color: '#78716c', marginBottom: 14, lineHeight: 1.5 }}>
              Describe <strong>ambient or camera motion</strong> — the subject is held still automatically.
              Avoid actions (“swings sword”, “runs”): image-to-video warps the figure on big moves.
            </div>
          </>)}

          {/* Motion strength — how much the art moves (LTX-Video) */}
          <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Motion strength</label>
          <select value={motionStrength} onChange={e => setMotionStrength(parseFloat(e.target.value))} style={selStyle}>
            <option value={0.2}>Subtle — barely-there drift</option>
            <option value={0.5}>Medium — gentle motion (default)</option>
            <option value={0.8}>Strong — pronounced movement</option>
          </select>
        </>)}

        {/* Foil style (only when foil is used) */}
        {usesFoil && (<>
          <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Foil style</label>
          <select value={foilStyle} onChange={e => setFoilStyle(e.target.value)} style={selStyle}>
            {foilList.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Foil intensity</label>
          <select value={foilIntensity} onChange={e => setFoilIntensity(parseFloat(e.target.value))} style={selStyle}>
            <option value={0.35}>Subtle</option>
            <option value={0.55}>Medium</option>
            <option value={0.8}>Strong</option>
          </select>
        </>)}

        {/* Clip length (duration) + frame rate */}
        <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span>Clip length</span>
          <span style={{ color: '#7dd3fc', fontWeight: 600 }}>{clampedDur.toFixed(1)}s</span>
        </label>
        <input type="range" min={range.min_s} max={range.max_s} step={0.5}
               value={clampedDur} onChange={e => setDuration(parseFloat(e.target.value))}
               style={{ width: '100%', marginBottom: 6, accentColor: '#0ea5e9' }} />
        <div style={{ fontSize: 11, color: '#78716c', marginBottom: 14 }}>
          ≈ {estFrames} frames{usesMotion ? ' (snapped to the model’s cadence)' : ''} ·
          {' '}plays ~{onScreenS}s on screen{loopMult > 1 ? ' (ping-pong loop)' : ''}.
          {usesMotion && <span> Longer = sharper motion but slower to render.</span>}
        </div>

        <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Smoothness (frame rate)</label>
        <select value={fps} onChange={e => setFps(parseInt(e.target.value, 10))} style={selStyle}>
          {fpsOptions.map(f => (
            <option key={f} value={f}>{f} fps{f <= 12 ? ' — choppy, tiny file' : f >= 30 ? ' — smoothest, larger file' : ''}</option>
          ))}
        </select>

        {/* Output format */}
        <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Format</label>
        <select value={fmt} onChange={e => setFmt(e.target.value)} style={selStyle}>
          {fmtList.map(f => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
        {fmt === 'gif' && (
          <div style={{ fontSize: 11, color: '#a8729e', marginTop: -8, marginBottom: 12 }}>
            GIF is the most portable but 256-colour — holo gradients band and files are large. WebP looks far better.
          </div>
        )}

        {/* Loop style (motion only — foil is inherently seamless) */}
        {usesMotion ? (<>
          <label style={{ fontSize: 12, color: '#d6d3d1', fontWeight: 700, display: 'block', marginBottom: 6 }}>Loop style</label>
          <select value={loopStyle} onChange={e => setLoopStyle(e.target.value)} style={{ ...selStyle, marginBottom: 4 }}>
            {(loopStyles?.length ? loopStyles : [
              { key: 'crossfade', label: 'Crossfade (smooth, forward-only)' },
              { key: 'bounce', label: 'Bounce (ping-pong)' },
              { key: 'off', label: 'No loop (play once)' },
            ]).map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <div style={{ fontSize: 11, color: '#78716c', marginBottom: 18, lineHeight: 1.5 }}>
            {loopStyle === 'bounce'
              ? 'Plays forward then reverse — seamless, but the motion visibly runs backward at the turn. Best for symmetric shimmer.'
              : loopStyle === 'off'
              ? 'Plays once and stops.'
              : 'Forward-only with a dissolved wrap — the most natural seamless loop for camera/ambient motion (slight ghosting during the dissolve).'}
          </div>
        </>) : (
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 18 }}>Foil loops seamlessly (always on).</div>
        )}

        {/* Selected card list */}
        <div style={{ fontSize: 11, color: '#78716c', marginBottom: 6 }}>Cards</div>
        <div style={{ maxHeight: 180, overflowY: 'auto', border: '1px solid #292524', borderRadius: 8, padding: 8, marginBottom: 18 }}>
          {selectedCards.map((c, i) => (
            <div key={i} style={{ fontSize: 12, color: '#d6d3d1', padding: '2px 0' }}>
              {c.themed_name}{c.themed_name !== c.original_name && <span style={{ color: '#57534e' }}> ({c.original_name})</span>}
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button onClick={onClose} style={{ ...btnBase, background: 'none', color: '#a8a29e', border: '1px solid #44403c' }}>
            Cancel
          </button>
          <button onClick={handleStart} disabled={!canRun}
            title={canRun ? '' : (health?.hint || 'Image-to-video model not available')}
            style={{ ...btnBase, background: '#0c2a4d', color: '#7dd3fc', border: '1px solid #0ea5e9',
              opacity: canRun ? 1 : 0.5, cursor: canRun ? 'pointer' : 'not-allowed' }}>
            ✨ Animate
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export default function StepDeck({ deck, jobId, onReset, onRebuild, onRetheme, onDuplicate, onEdit }) {
  const [filter, setFilter]   = useState('All')
  const [view, setView]       = useState('gallery')

  // ── Selection state ───────────────────────────────────────────────────────
  const [selectedKeys, setSelectedKeys]   = useState(new Set())
  const [showRegenPanel, setShowRegenPanel] = useState(false)

  // ── Per-card regen state ──────────────────────────────────────────────────
  const [regenJobId, setRegenJobId]         = useState(null)
  const [regenPending, setRegenPending]     = useState(new Set())   // render_keys in-flight
  const [regenDone, setRegenDone]           = useState(new Set())   // render_keys finished
  const [refreshTs, setRefreshTs]           = useState({})          // render_key → timestamp
  const [regenProgress, setRegenProgress]   = useState(null)        // {current, total, cardName}

  // ── Rebuild-all / retheme / duplicate state ───────────────────────────────
  const [rebuilding, setRebuilding]   = useState(false)
  const [showRebuildModal, setShowRebuildModal] = useState(false)
  const [rebuildArtStyle, setRebuildArtStyle] = useState(deck.art_style || 'mtg_fantasy')
  const [rebuildModelSpeed, setRebuildModelSpeed] = useState(deck.model_speed || 'quality')
  const [rebuildArtStyles, setRebuildArtStyles] = useState([])
  // Pinned style-variant for the rebuild — seeded from the deck's persisted choice.
  const [rebuildVariant, setRebuildVariant] = useState(deck.gen_settings?.style_variant || '')
  const [rethemeing, setRethemeing]   = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [dupMsg, setDupMsg]           = useState(null)   // null | {newJobId, name} | 'error'
  const [deckCheckpoints, setDeckCheckpoints] = useState([])

  // ── Animate (image-to-video) state ────────────────────────────────────────
  const [showAnimatePanel, setShowAnimatePanel] = useState(false)
  const [videoTs, setVideoTs]       = useState({})   // render_key → timestamp (cache-bust)
  const [videoKeys, setVideoKeys]   = useState(() => {
    const s = new Set()
    if (deck?.commander?.has_video) s.add(deck.commander.render_key)
    for (const c of deck?.deck || []) if (c.has_video) s.add(c.render_key)
    return s
  })
  const [videoFmts, setVideoFmts]   = useState(() => {   // render_key → mp4|webp|gif
    const m = {}
    const add = c => { if (c?.has_video) m[c.render_key] = c.video_meta?.format || 'mp4' }
    add(deck?.commander)
    for (const c of deck?.deck || []) add(c)
    return m
  })
  // View preference: show the animated version of cards that have one, or the
  // static still. Persisted across decks; default ON.
  const [showMotion, setShowMotion] = useState(() => {
    try { return localStorage.getItem('mtg_show_motion') !== '0' } catch { return true }
  })
  useEffect(() => {
    try { localStorage.setItem('mtg_show_motion', showMotion ? '1' : '0') } catch {}
  }, [showMotion])
  const [videoHealth, setVideoHealth] = useState(null)   // null | {ok, method, hint, ...}
  const [motionPresets, setMotionPresets] = useState([])
  const [foilStyles, setFoilStyles]       = useState([])
  const [videoFormats, setVideoFormats]   = useState([])
  const [videoLoopStyles, setVideoLoopStyles] = useState([])
  const [videoCaps, setVideoCaps]         = useState(null)   // {motion:{min_s,max_s,default_s}, foil:{...}, fps_options}

  // ── 3D Commander generation state ─────────────────────────────────────────
  const [gen3dState, setGen3dState]     = useState('idle')   // idle|loading|rmbg|trellis|converting|done|error
  const [gen3dMsg, setGen3dMsg]         = useState('')
  const [gen3dStlUrl, setGen3dStlUrl]   = useState(null)
  const [gen3dHealth, setGen3dHealth]   = useState(null)     // null | {ok, message, hint, missing}
  const [rebuildCheckpoint, setRebuildCheckpoint] = useState(deck.checkpoint || null)

  const evtRef = useRef(null)

  if (!deck) return null

  // ── Fetch art styles and checkpoints for rebuild modal ─────────────────────
  useEffect(() => {
    fetch('/api/art-styles')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setRebuildArtStyles(d) })
      .catch(() => {})
    fetch('/api/checkpoints')
      .then(r => r.ok ? r.json() : [])
      .then(d => setDeckCheckpoints(Array.isArray(d) ? d : []))
      .catch(() => {})
    fetch('/api/video-health')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setVideoHealth(d) })
      .catch(() => {})
    fetch('/api/video-presets')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.presets) setMotionPresets(d.presets)
        if (d?.foil_styles) setFoilStyles(d.foil_styles)
        if (d?.formats) setVideoFormats(d.formats)
        if (d?.loop_styles) setVideoLoopStyles(d.loop_styles)
        if (d?.caps) setVideoCaps(d.caps)
      })
      .catch(() => {})
  }, [])

  // ── SSE listener for per-card regen job ───────────────────────────────────
  useEffect(() => {
    if (!regenJobId) return
    const src = new EventSource(`/api/deck/${regenJobId}/events`)
    evtRef.current = src

    src.addEventListener('progress', e => {
      try {
        const d = JSON.parse(e.data)
        if ((d.step === 'art' || d.step === 'video') && d.card_num != null) {
          setRegenProgress({ current: d.card_num, total: d.total, cardName: d.card_name,
                             pct: d.pct, kind: d.step })
        }
      } catch {}
    })

    src.addEventListener('card_ready', e => {
      try {
        const d = JSON.parse(e.data)
        setRefreshTs(prev => ({ ...prev, [d.key]: Date.now() }))
        setRegenPending(prev => { const s = new Set(prev); s.delete(d.key); return s })
        setRegenDone(prev => new Set([...prev, d.key]))
        // A regenerated still invalidates its animation (it was made from the old
        // art); the backend deletes the stale clip, so drop the tile's video and
        // show the fresh still until the card is re-animated.
        setVideoKeys(prev => { if (!prev.has(d.key)) return prev; const s = new Set(prev); s.delete(d.key); return s })
        setVideoFmts(prev => { if (!(d.key in prev)) return prev; const m = { ...prev }; delete m[d.key]; return m })
      } catch {}
    })

    // Animate job: a card's MP4 just finished — swap its tile to the looping video.
    src.addEventListener('video_ready', e => {
      try {
        const d = JSON.parse(e.data)
        setVideoKeys(prev => new Set([...prev, d.key]))
        setVideoFmts(prev => ({ ...prev, [d.key]: d.format || 'mp4' }))
        setVideoTs(prev => ({ ...prev, [d.key]: Date.now() }))
        setRegenPending(prev => { const s = new Set(prev); s.delete(d.key); return s })
        setRegenDone(prev => new Set([...prev, d.key]))
      } catch {}
    })

    src.addEventListener('done', () => {
      src.close()
      setRegenJobId(null)
      setRegenPending(new Set())
      setRegenProgress(null)
      setSelectedKeys(new Set())
      setShowRegenPanel(false)
    })

    src.addEventListener('error', e => {
      if (!e.data) return   // connection-level reconnect, not a real error
      src.close()
      setRegenJobId(null)
      setRegenPending(new Set())
      setRegenProgress(null)
      try { alert(`Regen failed: ${JSON.parse(e.data).msg}`) } catch {}
    })

    src.onerror = () => {
      fetch(`/api/deck/${regenJobId}/status`).then(r => r.json()).then(d => {
        if (d.status === 'done' || d.status === 'error') {
          src.close(); setRegenJobId(null); setRegenPending(new Set()); setRegenProgress(null)
        }
      }).catch(() => {})
    }

    return () => src.close()
  }, [regenJobId])

  // ── Selection helpers ─────────────────────────────────────────────────────
  function toggleSelect(key) {
    setSelectedKeys(prev => {
      const s = new Set(prev)
      s.has(key) ? s.delete(key) : s.add(key)
      return s
    })
  }
  function clearSelection() { setSelectedKeys(new Set()) }

  // ── Regen handlers ────────────────────────────────────────────────────────
  async function handleStartRegen(payload) {
    setShowRegenPanel(false)
    setRegenPending(new Set(payload.cards.map(c => c.render_key)))
    try {
      const res = await fetch(`/api/deck/${jobId}/regen-cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRegenJobId(data.job_id)
    } catch (err) {
      setRegenPending(new Set())
      alert(`Could not start regen: ${err.message}`)
    }
  }

  async function handleStartAnimate(payload) {
    setShowAnimatePanel(false)
    setRegenPending(new Set(payload.cards.map(c => c.render_key)))
    try {
      const res = await fetch(`/api/deck/${jobId}/animate-cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRegenJobId(data.job_id)   // reuse the SSE listener (progress + video_ready + done)
    } catch (err) {
      setRegenPending(new Set())
      alert(`Could not start animation: ${err.message}`)
    }
  }

  async function handleRebuildAll() {
    // Show the rebuild options modal
    setShowRebuildModal(true)
  }

  async function handleConfirmRebuild() {
    if (rebuilding) return
    setRebuilding(true)
    setShowRebuildModal(false)
    // Only send the pinned variant if it actually belongs to the chosen style.
    const _rbStyle = rebuildArtStyles.find(s => s.key === rebuildArtStyle)
    const _rbVariant = (_rbStyle?.variants || []).some(v => v.label === rebuildVariant)
      ? rebuildVariant : ''
    try {
      const res = await fetch(`/api/deck/${jobId}/rebuild`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          art_style:   rebuildArtStyle,
          model_speed: rebuildModelSpeed,
          checkpoint:  rebuildCheckpoint || null,
          face_key:    deck.face_key || null,
          face_gender: deck.face_gender || 'either',
          crew_key:    deck.crew_key || null,
          crew_gender: deck.crew_gender || 'either',
          // Preserve the deck's advanced settings and apply the chosen flavor.
          // '' = Variety mix (per-card rotation).
          gen_settings: { ...(deck.gen_settings || {}), style_variant: _rbVariant },
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      onRebuild(data.job_id)
    } catch (err) {
      alert(`Could not start rebuild: ${err.message}`)
      setRebuilding(false)
    }
  }

  async function handleRethemeAll() {
    if (rethemeing) return
    setRethemeing(true)
    try {
      const newJobId = await triggerRetheme(jobId)
      if (onRetheme) onRetheme(newJobId)
      else if (onRebuild) onRebuild(newJobId)  // fallback: treat like rebuild nav
    } catch (err) {
      alert(`Could not start retheme: ${err.message}`)
      setRethemeing(false)
    }
  }

  async function handleDuplicate() {
    if (duplicating) return
    setDuplicating(true)
    setDupMsg(null)
    try {
      const res = await fetch(`/api/deck/${jobId}/duplicate`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDupMsg({ newJobId: data.new_job_id, name: data.themed_name })
      if (onDuplicate) onDuplicate(data.new_job_id)
    } catch (err) {
      setDupMsg('error')
    } finally {
      setDuplicating(false)
    }
  }

  // ── 3D generation handler ────────────────────────────────────────────────
  async function handleGenerate3D() {
    if (gen3dState !== 'idle' && gen3dState !== 'error') return

    // Check health first
    setGen3dState('loading')
    setGen3dMsg('Checking 3D generation availability…')
    try {
      const hRes = await fetch('/api/3d-health')
      const health = await hRes.json()
      setGen3dHealth(health)
      if (!health.ok) {
        setGen3dState('error')
        setGen3dMsg(health.message)
        return
      }
    } catch (err) {
      setGen3dState('error')
      setGen3dMsg(`Health check failed: ${err.message}`)
      return
    }

    // Start generation
    setGen3dMsg('Queuing 3D generation…')
    try {
      const res = await fetch(`/api/deck/${jobId}/generate-3d`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        const detail = err.detail || {}
        setGen3dState('error')
        setGen3dMsg(typeof detail === 'string' ? detail : detail.message || `HTTP ${res.status}`)
        if (detail.hint) setGen3dHealth(h => ({ ...h, hint: detail.hint }))
        return
      }
      const { job_3d_id } = await res.json()

      // Open SSE stream
      setGen3dState('rmbg')
      setGen3dMsg('Removing background…')
      const es = new EventSource(`/api/deck/${jobId}/3d-status/${job_3d_id}`)
      // Tracks whether a terminal event (done / server-sent error) already
      // arrived, so the generic onerror connection handler doesn't clobber the
      // real message when the server closes the stream right after sending it.
      let settled = false

      es.addEventListener('progress', e => {
        const data = JSON.parse(e.data)
        const step = data.step || 'rmbg'
        const stateMap = { rmbg: 'rmbg', trellis: 'trellis', converting: 'converting' }
        setGen3dState(stateMap[step] || 'trellis')
        setGen3dMsg(data.msg || '')
      })

      es.addEventListener('done', e => {
        const data = JSON.parse(e.data)
        settled = true
        setGen3dState('done')
        setGen3dMsg('3D model ready!')
        setGen3dStlUrl(data.stl_url)
        es.close()
      })

      es.addEventListener('error', e => {
        // This listener fires for BOTH a backend-sent `event: error` (which has
        // e.data) and transport-level failures (no e.data). Only the former is a
        // real, final result — let transport errors fall through to es.onerror.
        if (!e.data) return
        let msg = 'Generation failed'
        try { msg = JSON.parse(e.data).msg || msg } catch {}
        settled = true
        setGen3dState('error')
        setGen3dMsg(msg)
        es.close()
      })

      es.onerror = () => {
        // Only a genuine connection drop — if the backend already told us the
        // outcome, keep that message instead of overwriting with a generic one.
        if (!settled) {
          setGen3dState('error')
          setGen3dMsg('Lost connection to the server before the 3D job reported a result. Check that the Myth Forge server and ComfyUI are still running.')
        }
        es.close()
      }
    } catch (err) {
      setGen3dState('error')
      setGen3dMsg(`Request failed: ${err.message}`)
    }
  }

  // ── Derived data ──────────────────────────────────────────────────────────
  const groups      = groupByType(deck.deck)
  const types       = ['All', ...TYPE_ORDER.filter(t => groups[t]?.length > 0)]
  if (groups['Other']?.length) types.push('Other')
  const visibleCards = filter === 'All' ? deck.deck : (groups[filter] || [])

  const allCardsFlat    = [deck.commander, ...deck.deck]
  const selectedCardData = allCardsFlat.filter(c => selectedKeys.has(c.render_key))

  const { commander, stats } = deck
  // Single custom-card mode: the deck is "of one", so deck-level chrome (stats,
  // type filters, the empty deck grid) is hidden and labels are re-pointed.
  const single = deck?.mode === 'single_card'

  function regenStatusFor(key) {
    if (regenPending.has(key)) return 'pending'
    if (regenDone.has(key))    return 'done'
    return 'idle'
  }

  const btnBase = { padding: '5px 14px', borderRadius: 8, fontFamily: 'inherit', fontSize: 12, cursor: 'pointer', border: '1px solid #44403c' }

  return (
    <div style={{ width: '100%', maxWidth: 1200, marginTop: 24, paddingBottom: selectedKeys.size > 0 || regenProgress ? 80 : 0 }}>

      {/* Commander banner */}
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 24, marginBottom: 24, alignItems: 'flex-start' }}>
        {/* Commander image — clickable for selection */}
        <div
          style={{ position: 'relative', flexShrink: 0, cursor: 'pointer' }}
          onClick={() => toggleSelect(commander.render_key)}
          title="Click to select commander for regen"
        >
          {(() => {
            const imgStyle = { width: 180, borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.6)', outline: selectedKeys.has(commander.render_key) ? '3px solid #eab308' : 'none', display: 'block' }
            const stillSrc = (commander.has_render || refreshTs[commander.render_key])
              ? `/api/deck/${jobId}/card-image/${commander.render_key}${refreshTs[commander.render_key] ? `?t=${refreshTs[commander.render_key]}` : ''}`
              : commander.scryfall_img || null
            // Show the animation when the commander has one (mp4 → <video>, webp/gif → <img>),
            // unless the viewer turned animations off.
            if (showMotion && videoKeys.has(commander.render_key)) {
              const vts  = videoTs[commander.render_key] || 0
              const vfmt = videoFmts[commander.render_key] || commander.video_meta?.format || 'mp4'
              const vsrc = `/api/deck/${jobId}/card-video/${commander.render_key}${vts ? `?t=${vts}` : ''}`
              return (vfmt === 'webp' || vfmt === 'gif')
                ? <img src={vsrc} alt={commander.themed_name} style={imgStyle} />
                : <video src={vsrc} poster={stillSrc || undefined} autoPlay loop muted playsInline preload="auto"
                    style={{ ...imgStyle, background: '#000' }} />
            }
            return stillSrc
              ? <img src={stillSrc} alt={commander.themed_name} style={imgStyle} />
              : <div style={{ width: 180, height: 252, background: '#0c0a09', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57534e' }}>No art</div>
          })()}
          {/* Status overlays for commander */}
          {regenPending.has(commander.render_key) && (
            <div style={{ position: 'absolute', inset: 0, borderRadius: 12, background: 'rgba(0,0,0,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 22, animation: 'spin-slow 1.5s linear infinite' }}>⚙️</div>
              <div style={{ fontSize: 9, color: '#eab308', fontWeight: 700 }}>Generating…</div>
            </div>
          )}
          {selectedKeys.has(commander.render_key) && !regenPending.has(commander.render_key) && (
            <div style={{ position: 'absolute', top: 6, right: 6, width: 22, height: 22, borderRadius: '50%', background: '#eab308', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 900, color: '#0c0a09' }}>✓</div>
          )}
          {regenDone.has(commander.render_key) && !regenPending.has(commander.render_key) && (
            <div style={{ position: 'absolute', top: 6, left: 6, fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 700, background: '#14532d', color: '#86efac', border: '1px solid #166534' }}>NEW</div>
          )}
          <div style={{ position: 'absolute', bottom: 6, left: '50%', transform: 'translateX(-50%)', fontSize: 9, color: '#78716c', whiteSpace: 'nowrap', background: 'rgba(0,0,0,0.6)', padding: '2px 6px', borderRadius: 4 }}>
            click to select
          </div>
        </div>

        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <div style={{ fontSize: 11, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 6 }}>{single ? 'Custom Card' : 'Commander'}</div>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: '#fde047', margin: '0 0 4px', lineHeight: 1.2, overflowWrap: 'anywhere' }}>{commander.themed_name}</h1>
          {commander.themed_name !== commander.original_name && (
            <div style={{ fontSize: 13, color: '#57534e', marginBottom: 10 }}>({commander.original_name})</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <ManaCost cost={commander.mana_cost} size={20} />
          </div>
          <div style={{ fontSize: 13, color: '#a8a29e', marginBottom: 6 }}>{commander.type_line}</div>
          <div style={{ fontSize: 12, color: '#d6d3d1', lineHeight: 1.6, marginBottom: 16, maxWidth: 440 }}>{commander.oracle_text}</div>
          {commander.flavor_text && (
            <div style={{ fontSize: 12, color: '#78716c', fontStyle: 'italic', marginBottom: 16, maxWidth: 440 }}>{commander.flavor_text}</div>
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {!single && <span style={{ fontSize: 12, padding: '4px 12px', background: '#422006', border: '1px solid #ca8a04', borderRadius: 20, color: '#fde047' }}>{deck.playstyle}</span>}
            {!single && deck.bracket && (
              <span style={{ fontSize: 12, padding: '4px 12px', borderRadius: 20, fontWeight: 700,
                background: ['','#052e16','#1a2e05','#422006','#431407','#450a0a'][deck.bracket] || '#1c1917',
                border: `1px solid ${['','#4ade80','#a3e635','#eab308','#f97316','#ef4444'][deck.bracket] || '#44403c'}`,
                color: ['','#4ade80','#a3e635','#eab308','#f97316','#ef4444'][deck.bracket] || '#a8a29e',
              }}>
                B{deck.bracket} {deck.bracket_label}
              </span>
            )}
            {deck.theme && <span style={{ fontSize: 12, padding: '4px 12px', background: '#0c0a09', border: '1px solid #292524', borderRadius: 20, color: '#a8a29e' }}>{deck.theme}</span>}
            {!single && <span style={{ fontSize: 12, padding: '4px 12px', background: '#0c0a09', border: '1px solid #292524', borderRadius: 20, color: '#a8a29e' }}>{stats?.total_cards || deck.deck.length + 1} cards</span>}
            {!single && deck.collection && deck.collection.enabled && (
              <span title={`From your Myth Suite collection (${deck.collection.collection_size} owned cards)`}
                    style={{ fontSize: 12, padding: '4px 12px', background: '#052e16',
                             border: '1px solid #16a34a', borderRadius: 20, color: '#4ade80' }}>
                🎴 {deck.collection.owned}/{deck.collection.total} from your collection
              </span>
            )}
          </div>

          {/* Playstyle strategy summary */}
          {deck.playstyle_description && (
            <div style={{ fontSize: 12.5, color: '#a8a29e', lineHeight: 1.55, marginTop: 12, maxWidth: 460 }}>
              <span style={{ color: '#fde047', fontWeight: 700 }}>Strategy: </span>{deck.playstyle_description}
            </div>
          )}
          {/* Deck composition one-liner */}
          {stats?.type_counts && (
            <div style={{ fontSize: 11.5, color: '#78716c', marginTop: 8, maxWidth: 460 }}>
              {['Creature','Instant','Sorcery','Artifact','Enchantment','Planeswalker','Land']
                .filter(t => stats.type_counts[t])
                .map(t => `${stats.type_counts[t]} ${t.toLowerCase()}${stats.type_counts[t] > 1 ? (t === 'Sorcery' ? ' sorceries' : 's') : ''}`)
                .join(' · ')}
              {stats.average_cmc != null && ` · avg MV ${stats.average_cmc.toFixed(1)}`}
            </div>
          )}

          {/* ── 3D Commander Generator ─────────────────────────────────────── */}
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #292524' }}>
            <div style={{ fontSize: 10, color: '#57534e', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>3D Print</div>

            {gen3dState === 'idle' || gen3dState === 'error' ? (
              <div>
                <button
                  onClick={handleGenerate3D}
                  style={{
                    fontSize: 13, padding: '8px 18px', borderRadius: 8, border: '1px solid #44403c',
                    background: '#1c1917', color: '#d6d3d1', cursor: 'pointer', fontFamily: 'inherit',
                    display: 'flex', alignItems: 'center', gap: 8,
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = '#292524'}
                  onMouseLeave={e => e.currentTarget.style.background = '#1c1917'}
                >
                  <span style={{ fontSize: 16 }}>🧊</span>
                  Generate 3D Model (STL)
                </button>
                {gen3dState === 'error' && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, color: '#f87171', marginBottom: 4 }}>⚠ {gen3dMsg}</div>
                    {gen3dHealth?.hint && (
                      <div style={{ fontSize: 11, color: '#57534e' }}>{gen3dHealth.hint}</div>
                    )}
                    {gen3dHealth?.missing?.length > 0 && (
                      <div style={{ marginTop: 6, padding: '8px 10px', background: '#1c1917', borderRadius: 6, border: '1px solid #292524' }}>
                        <div style={{ fontSize: 11, color: '#78716c', marginBottom: 4 }}>Missing models:</div>
                        {gen3dHealth.missing.map(m => (
                          <div key={m} style={{ fontSize: 11, color: '#a8a29e', fontFamily: 'monospace' }}>• {m}</div>
                        ))}
                        <div style={{ fontSize: 11, color: '#57534e', marginTop: 4 }}>
                          Run: <code style={{ color: '#86efac' }}>python model3d.py --download-models</code>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : gen3dState === 'done' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <a
                  href={gen3dStlUrl}
                  download
                  style={{
                    fontSize: 13, padding: '8px 18px', borderRadius: 8, border: '1px solid #166534',
                    background: '#14532d', color: '#86efac', cursor: 'pointer', fontFamily: 'inherit',
                    display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none',
                  }}
                >
                  <span style={{ fontSize: 16 }}>⬇</span>
                  Download STL
                </a>
                <button
                  onClick={() => { setGen3dState('idle'); setGen3dStlUrl(null); setGen3dMsg('') }}
                  style={{ fontSize: 12, padding: '6px 12px', borderRadius: 6, border: '1px solid #292524', background: '#1c1917', color: '#78716c', cursor: 'pointer', fontFamily: 'inherit' }}
                  title="Generate again with a new random seed"
                >↺ Regenerate</button>
              </div>
            ) : (
              /* loading / rmbg / trellis / converting */
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <div style={{ fontSize: 18, animation: 'spin-slow 1.5s linear infinite' }}>⚙️</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 4 }}>
                      {gen3dState === 'loading'    && '🔍 Checking system…'}
                      {gen3dState === 'rmbg'       && '✂️ Removing background…'}
                      {gen3dState === 'trellis'    && '🧊 Generating 3D mesh (Hunyuan3D v2)…'}
                      {gen3dState === 'converting' && '🔧 Exporting STL…'}
                    </div>
                    {/* Progress steps */}
                    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      {[
                        { key: 'rmbg',       label: 'BG Removal',  icon: '✂️' },
                        { key: 'trellis',    label: '3D Mesh',     icon: '🧊' },
                        { key: 'converting', label: 'STL Export',  icon: '🔧' },
                      ].map((step, i) => {
                        const stepOrder = { loading: -1, rmbg: 0, trellis: 1, converting: 2, done: 3 }
                        const current  = stepOrder[gen3dState] ?? 0
                        const mine     = i
                        const active   = current === mine
                        const done     = current > mine
                        return (
                          <div key={step.key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <div style={{
                              fontSize: 10, padding: '2px 8px', borderRadius: 10,
                              background: done ? '#14532d' : active ? '#422006' : '#0c0a09',
                              border: `1px solid ${done ? '#166534' : active ? '#ca8a04' : '#292524'}`,
                              color: done ? '#86efac' : active ? '#fde047' : '#57534e',
                            }}>
                              {done ? '✓ ' : active ? '⟳ ' : ''}{step.label}
                            </div>
                            {i < 2 && <div style={{ width: 16, height: 1, background: '#292524' }} />}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
                {gen3dMsg && (
                  <div style={{ fontSize: 11, color: '#57534e', fontFamily: 'monospace', marginTop: 4 }}>
                    {gen3dMsg}
                  </div>
                )}
                <div style={{ fontSize: 11, color: '#57534e', marginTop: 4 }}>
                  ⏱ 3D mesh generation takes 2–5 minutes on RTX 3090
                </div>
              </div>
            )}
          </div>
          {/* ── end 3D generator ──────────────────────────────────────────── */}
        </div>

        {/* Stats panel */}
        {!single && stats && (
          <div style={{ width: 200, flexShrink: 0 }}>
            <div style={{ fontSize: 12, color: '#78716c', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Deck Stats</div>
            <div style={{ fontSize: 13, color: '#a8a29e', marginBottom: 4 }}>Avg CMC: <span style={{ color: '#fde047', fontWeight: 700 }}>{(stats.average_cmc ?? stats.avg_cmc)?.toFixed?.(2) ?? '—'}</span></div>
            <div style={{ height: 1, background: '#292524', margin: '10px 0' }} />
            {stats.type_counts && Object.entries(stats.type_counts).map(([type, count]) => (
              <StatBar key={type} label={type} value={count} max={30} color='#ca8a04' />
            ))}
            {stats.cmc_curve && <div style={{ marginTop: 12 }}><CmcChart curve={stats.cmc_curve} /></div>}
            <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
            <div style={{ fontSize: 12, color: '#a8a29e' }}>Lands: <span style={{ color: '#86efac' }}>{stats.land_count}</span></div>
            {/* Color identity (mana pip counts) */}
            {stats.color_pips && Object.keys(stats.color_pips).length > 0 && (
              <>
                <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
                <div style={{ fontSize: 11, color: '#78716c', marginBottom: 6 }}>Color pips</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {Object.entries(stats.color_pips).map(([c, n]) => (
                    <span key={c} style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11,
                      padding: '2px 8px', borderRadius: 12,
                      background: { W:'#3a3526', U:'#0c2748', B:'#2b2735', R:'#3a1414', G:'#11331c', C:'#1c1917' }[c] || '#1c1917',
                      color:      { W:'#f5e6c8', U:'#7dd3fc', B:'#c4b5fd', R:'#fca5a5', G:'#86efac', C:'#a8a29e' }[c] || '#a8a29e',
                    }}>{c} {n}</span>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Type filter */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: 1 }}>
          {!single && types.map(t => (
            <button key={t} onClick={() => setFilter(t)} style={{
              fontSize: 12, padding: '5px 14px', borderRadius: 20, border: 'none', cursor: 'pointer', fontFamily: 'inherit',
              background: filter === t ? '#ca8a04' : '#1c1917',
              color: filter === t ? '#0c0a09' : '#a8a29e',
              fontWeight: filter === t ? 700 : 400,
            }}>
              {t} {t !== 'All' && groups[t] ? `(${groups[t].length})` : t === 'All' ? `(${deck.deck.length})` : ''}
            </button>
          ))}
        </div>

        {/* View toggle */}
        <div style={{ display: 'flex', gap: 4 }}>
          {['gallery', 'list'].map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              padding: '5px 14px', borderRadius: 8, border: '1px solid #292524', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12,
              background: view === v ? '#292524' : 'transparent', color: view === v ? '#f5f5f4' : '#57534e',
            }}>
              {v === 'gallery' ? '⊞ Gallery' : '☰ List'}
            </button>
          ))}
        </div>

        {/* Export + actions */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button onClick={() => exportMoxfield(deck)} style={{ ...btnBase, background: 'none', color: '#a8a29e' }}>Moxfield</button>
          <button onClick={() => exportThemed(deck)}   style={{ ...btnBase, background: 'none', color: '#a8a29e' }}>Themed TXT</button>
          <button onClick={() => triggerDownload(`/api/deck/${jobId}/export/zip`)} style={{ ...btnBase, background: '#1e3a5f', color: '#93c5fd', border: '1px solid #1d4ed8', fontWeight: 600 }}>↓ ZIP</button>
          <button onClick={() => triggerDownload(`/api/deck/${jobId}/export/pdf`)} style={{ ...btnBase, background: '#14532d', color: '#86efac', border: '1px solid #15803d', fontWeight: 600 }}>↓ PDF</button>
          {videoKeys.size > 0 && (
            <button onClick={() => triggerDownload(`/api/deck/${jobId}/export/videos`)} style={{ ...btnBase, background: '#0c2a4d', color: '#7dd3fc', border: '1px solid #0ea5e9', fontWeight: 600 }}>🎬 Animations ({videoKeys.size})</button>
          )}
          {videoKeys.size > 0 && (
            <button
              onClick={() => setShowMotion(m => !m)}
              title={showMotion ? 'Showing animated cards — click to show the static art instead'
                                : 'Showing static art — click to play the animated versions'}
              style={{ ...btnBase, background: showMotion ? '#0c2a4d' : 'none',
                color: showMotion ? '#7dd3fc' : '#78716c',
                border: `1px solid ${showMotion ? '#0ea5e9' : '#44403c'}`, fontWeight: 600 }}
            >{showMotion ? '▶ Motion: On' : '❚❚ Motion: Off'}</button>
          )}
          <button
            onClick={handleRethemeAll}
            disabled={rethemeing || rebuilding}
            title="Re-kick the FULL generation on the same cards: new names, text/flavor AND freshly generated art (same theme + settings). Creates a new deck; this one is kept."
            style={{ ...btnBase, background: rethemeing ? '#1e1b4b' : '#1e3a5f', color: rethemeing ? '#818cf8' : '#93c5fd', border: `1px solid ${rethemeing ? '#4f46e5' : '#1d4ed8'}`, fontWeight: 600, opacity: rethemeing ? 0.7 : 1 }}
          >
            {rethemeing ? '⏳ Starting…' : '✏️ Retheme'}
          </button>
          {onRebuild && (
            <button onClick={handleRebuildAll} disabled={rebuilding || rethemeing} title="Re-generate ALL card art with new seeds — keeps the current names &amp; prompts (just re-rolls the art)."
              style={{ ...btnBase, background: rebuilding ? '#2e1065' : '#3b0764', color: rebuilding ? '#7c3aed' : '#c4b5fd', border: '1px solid #7c3aed', fontWeight: 600, opacity: rebuilding ? 0.7 : 1 }}>
              {rebuilding ? '⏳ Starting…' : '🔄 Rebuild All'}
            </button>
          )}
          {onEdit && (
            <button
              onClick={() => onEdit(deck)}
              disabled={rebuilding || rethemeing || duplicating}
              title="Re-open the builder with this deck's commander, theme, prompts, art style and all settings pre-filled for editing. Building creates a new deck — this one is kept."
              style={{ ...btnBase, background: '#1c1408', color: '#fde047', border: '1px solid #ca8a04', fontWeight: 600 }}
            >
              🎛️ Edit &amp; Rebuild
            </button>
          )}
          <button
            onClick={handleDuplicate}
            disabled={duplicating || rebuilding || rethemeing}
            title="Create an independent copy of this deck — the original is preserved unchanged"
            style={{ ...btnBase, background: duplicating ? '#1c2030' : '#0f172a', color: duplicating ? '#64748b' : '#7dd3fc', border: '1px solid #1e40af', fontWeight: 600, opacity: duplicating ? 0.7 : 1 }}
          >
            {duplicating ? '⏳ Copying…' : '📋 Duplicate'}
          </button>
          <button onClick={onReset} style={{ ...btnBase, background: 'linear-gradient(180deg,#eab308,#a16207)', color: '#0c0a09', border: 'none', fontWeight: 700 }}>New Deck</button>
        </div>
        {/* Duplicate feedback banner */}
        {dupMsg && dupMsg !== 'error' && (
          <div style={{ marginTop: 8, padding: '8px 14px', background: '#0c1a2e', border: '1px solid #1e40af', borderRadius: 8, fontSize: 12, color: '#7dd3fc', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📋</span>
            <span>Copy created: <strong>{dupMsg.name || dupMsg.newJobId}</strong> — find it in History.</span>
          </div>
        )}
        {dupMsg === 'error' && (
          <div style={{ marginTop: 8, padding: '8px 14px', background: '#1c0a0a', border: '1px solid #7f1d1d', borderRadius: 8, fontSize: 12, color: '#fca5a5' }}>
            ⚠ Duplicate failed. Check that the deck has finished building.
          </div>
        )}
      </div>

      {/* Selection hint */}
      {selectedKeys.size === 0 && !regenProgress && view === 'gallery' && (
        <div style={{ fontSize: 11, color: '#44403c', marginBottom: 12, textAlign: 'center' }}>
          Click any card to select it for regeneration
        </div>
      )}

      {/* Card gallery */}
      {view === 'gallery' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
          {visibleCards.map((card, i) => (
            <CardTile
              key={`${card.original_name}-${i}`}
              card={card}
              jobId={jobId}
              selected={selectedKeys.has(card.render_key)}
              onSelect={!regenProgress ? toggleSelect : null}
              regenStatus={regenStatusFor(card.render_key)}
              refreshTs={refreshTs[card.render_key] || 0}
              hasVideo={videoKeys.has(card.render_key)}
              showMotion={showMotion}
              videoTs={videoTs[card.render_key] || 0}
              videoFmt={videoFmts[card.render_key]}
            />
          ))}
        </div>
      )}

      {/* List view */}
      {view === 'list' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {(filter === 'All' ? TYPE_ORDER.concat('Other') : [filter]).map(type => {
            const cards = groups[type]
            if (!cards?.length) return null
            return (
              <div key={type} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '6px 0', borderBottom: '1px solid #1c1917', marginBottom: 6 }}>
                  {type} ({cards.length})
                </div>
                {cards.map((c, i) => (
                  <div key={i}
                    onClick={() => !regenProgress && toggleSelect(c.render_key)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 12, padding: '7px 8px', borderRadius: 6,
                      background: selectedKeys.has(c.render_key) ? '#1c1408' : i % 2 === 0 ? '#0c0a09' : 'transparent',
                      cursor: 'pointer',
                      outline: selectedKeys.has(c.render_key) ? '1px solid #ca8a04' : 'none',
                    }}
                  >
                    <div style={{ width: 16, height: 16, borderRadius: '50%', flexShrink: 0,
                      background: selectedKeys.has(c.render_key) ? '#eab308' : '#1c1917',
                      border: `1px solid ${selectedKeys.has(c.render_key) ? '#eab308' : '#44403c'}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 900, color: '#0c0a09',
                    }}>{selectedKeys.has(c.render_key) ? '✓' : ''}</div>
                    <ManaCost cost={c.mana_cost} size={16} />
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: '#f5f5f4' }}>{c.themed_name}</span>
                    {c.themed_name !== c.original_name && <span style={{ fontSize: 11, color: '#57534e' }}>({c.original_name})</span>}
                    <span style={{ fontSize: 11, color: '#44403c', minWidth: 100, textAlign: 'right' }}>{c.type_line?.replace('Legendary ', '').replace(' — ', ' ')}</span>
                    {c.power && <span style={{ fontSize: 11, color: '#78716c', minWidth: 30, textAlign: 'right' }}>{c.power}/{c.toughness}</span>}
                    {regenStatusFor(c.render_key) === 'pending' && <span style={{ fontSize: 10, color: '#eab308' }}>⚙️</span>}
                    {regenStatusFor(c.render_key) === 'done'    && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: '#14532d', color: '#86efac', fontWeight: 700 }}>NEW</span>}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}

      {/* ── Fixed bottom bar: selection actions ── */}
      {selectedKeys.size > 0 && !regenProgress && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 100,
          background: '#1c1917', borderTop: '1px solid #44403c',
          padding: '12px 24px', display: 'flex', alignItems: 'center', gap: 14,
          boxShadow: '0 -4px 24px rgba(0,0,0,0.5)',
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: '#fde047' }}>
            {selectedKeys.size} card{selectedKeys.size !== 1 ? 's' : ''} selected
          </span>
          <div style={{ flex: 1 }} />
          <button
            onClick={() => setSelectedKeys(new Set(visibleCards.map(c => c.render_key)))}
            style={{ ...btnBase, background: 'none', color: '#78716c', fontSize: 11 }}
          >Select visible</button>
          <button
            onClick={clearSelection}
            style={{ ...btnBase, background: 'none', color: '#78716c', fontSize: 11 }}
          >✕ Clear</button>
          <button
            onClick={() => setShowAnimatePanel(true)}
            title={videoHealth?.ok ? 'Animate the selected cards (art motion and/or foil sheen)'
                                   : 'Add a foil/holo sheen (a video model is needed for art motion)'}
            style={{ ...btnBase,
              background: '#0c2a4d', color: '#7dd3fc', border: '1px solid #0ea5e9',
              fontWeight: 700, fontSize: 13, padding: '8px 18px', cursor: 'pointer' }}
          >
            ✨ Animate {selectedKeys.size}
          </button>
          <button
            onClick={() => setShowRegenPanel(true)}
            style={{ ...btnBase, background: '#3b0764', color: '#c4b5fd', border: '1px solid #7c3aed', fontWeight: 700, fontSize: 13, padding: '8px 20px' }}
          >
            🎲 Regenerate {selectedKeys.size} Card{selectedKeys.size !== 1 ? 's' : ''}
          </button>
        </div>
      )}

      {/* ── Fixed bottom bar: regen progress ── */}
      {regenProgress && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 100,
          background: '#1c1917', borderTop: '1px solid #44403c',
          padding: '10px 24px', display: 'flex', flexDirection: 'column', gap: 6,
          boxShadow: '0 -4px 24px rgba(0,0,0,0.5)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ fontSize: 13, animation: 'spin-slow 1.5s linear infinite' }}>⚙️</div>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#eab308' }}>
              {regenProgress.kind === 'video' ? 'Animating cards…' : 'Regenerating cards…'} {regenProgress.current}/{regenProgress.total}
            </span>
            {regenProgress.cardName && (
              <span style={{ fontSize: 12, color: '#78716c', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {regenProgress.cardName}
              </span>
            )}
            <span style={{ fontSize: 12, color: '#57534e' }}>{(regenProgress.pct || 0).toFixed(0)}%</span>
          </div>
          <div style={{ height: 4, background: '#292524', borderRadius: 2 }}>
            <div style={{ height: 4, background: '#7c3aed', borderRadius: 2, width: `${regenProgress.pct || 0}%`, transition: 'width 0.4s ease' }} />
          </div>
        </div>
      )}

      {/* ── Regen panel modal ── */}
      {showRegenPanel && (
        <RegenPanel
          selectedCards={selectedCardData}
          onStart={handleStartRegen}
          onClose={() => setShowRegenPanel(false)}
          defaultArtStyle={deck.art_style || 'mtg_fantasy'}
          defaultModelSpeed={deck.model_speed || 'quality'}
          defaultCheckpoint={deck.checkpoint || null}
          commanderOriginalName={deck.commander?.original_name}
          savedFaceKey={deck.face_key || null}
          savedFaceGender={deck.face_gender || 'either'}
          savedCrewKey={deck.crew_key || null}
          savedCrewGender={deck.crew_gender || 'either'}
        />
      )}

      {/* ── Animate panel modal ── */}
      {showAnimatePanel && (
        <AnimatePanel
          selectedCards={selectedCardData}
          presets={motionPresets}
          foilStyles={foilStyles}
          formats={videoFormats}
          loopStyles={videoLoopStyles}
          caps={videoCaps}
          health={videoHealth}
          onStart={handleStartAnimate}
          onClose={() => setShowAnimatePanel(false)}
        />
      )}

      {/* ── Rebuild modal ── */}
      {showRebuildModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 200, padding: 16,
        }}
          onClick={e => { if (e.target === e.currentTarget) setShowRebuildModal(false) }}
        >
          <div style={{
            background: '#1c1917', border: '1px solid #44403c', borderRadius: 16,
            width: '100%', maxWidth: 400, boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
            padding: 24, display: 'flex', flexDirection: 'column', gap: 16,
          }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, color: '#fde047', fontWeight: 700 }}>🔄 Rebuild Deck</h3>
              <div style={{ fontSize: 12, color: '#78716c', marginTop: 4 }}>
                Generate new card art with different settings
              </div>
            </div>

            <div>
              <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Art Style
              </label>
              <select
                value={rebuildArtStyle}
                onChange={e => setRebuildArtStyle(e.target.value)}
                style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 11, fontFamily: 'inherit', boxSizing: 'border-box' }}
              >
                {rebuildArtStyles.length > 0 ? (
                  rebuildArtStyles.map(s => (
                    <option key={s.key} value={s.key} disabled={!s.ready && !s.partial}>
                      {s.icon} {s.label}{s.ready ? '' : s.partial ? ' (partial)' : ' (missing)'}
                    </option>
                  ))
                ) : (
                  <option value="mtg_fantasy">MTG Fantasy</option>
                )}
              </select>
            </div>

            {/* Style-variant selector — only when the chosen style exposes flavors */}
            {(() => {
              const st = rebuildArtStyles.find(s => s.key === rebuildArtStyle)
              const variants = (st && Array.isArray(st.variants)) ? st.variants : []
              if (variants.length === 0) return null
              return (
                <div>
                  <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    {st.label} Flavor
                  </label>
                  <select
                    value={variants.some(v => v.label === rebuildVariant) ? rebuildVariant : ''}
                    onChange={e => setRebuildVariant(e.target.value)}
                    style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 11, fontFamily: 'inherit', boxSizing: 'border-box' }}
                  >
                    <option value="">✨ Variety mix (each card varies)</option>
                    {variants.map(v => (
                      <option key={v.label} value={v.label} disabled={!v.ready}>
                        {v.ready ? '✓' : '⚠'} {v.label}{v.ready ? '' : ' (LoRA missing)'}
                      </option>
                    ))}
                  </select>
                </div>
              )
            })()}

            <div>
              <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Image Model
              </label>
              {deckCheckpoints.length > 0 ? (() => {
                const activeCkpt   = deckCheckpoints.find(c => c.filename === rebuildCheckpoint)
                const activeType   = (activeCkpt?.type || '').toUpperCase()
                const isSchnellAct = rebuildCheckpoint?.toLowerCase().includes('schnell')
                const isDevAct     = activeType.includes('FLUX') && !isSchnellAct
                const isSDXLAct    = activeType.includes('SDXL')
                const isSd35Act    = activeType.includes('SD') && !isSDXLAct && !activeType.includes('FLUX')
                const hasDev_   = deckCheckpoints.some(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))
                const hasSch_   = deckCheckpoints.some(c => c.filename.toLowerCase().includes('schnell'))
                const hasSDXL_  = deckCheckpoints.some(c => (c.type||'').toUpperCase().includes('SDXL'))
                const hasSd35_  = deckCheckpoints.some(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') && !t.includes('FLUX') })
                const pickRebuild = (fn, speed) => { setRebuildCheckpoint(fn || null); if (speed) setRebuildModelSpeed(speed) }
                const btnSt = { padding: '8px 12px', borderRadius: 8, fontSize: 11, fontFamily: 'inherit', cursor: 'pointer', border: '1px solid #292524', flex: 1, textAlign: 'left' }
                return (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {hasDev_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))?.filename, 'quality')}
                        style={{ ...btnSt, background: isDevAct ? '#1c1410' : '#0c0a09', color: isDevAct ? '#eab308' : '#a8a29e', borderColor: isDevAct ? '#ca8a04' : '#292524', fontWeight: isDevAct ? 700 : 400 }}>
                        <div>✦ Quality</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>FLUX Dev</div>
                      </button>
                    )}
                    {hasSDXL_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => (c.type||'').toUpperCase().includes('SDXL'))?.filename, null)}
                        style={{ ...btnSt, background: isSDXLAct ? '#120a1e' : '#0c0a09', color: isSDXLAct ? '#a78bfa' : '#a8a29e', borderColor: isSDXLAct ? '#a78bfa' : '#292524', fontWeight: isSDXLAct ? 700 : 400 }}>
                        <div>🎨 Illustrious XL</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>SDXL</div>
                      </button>
                    )}
                    {hasSd35_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') && !t.includes('FLUX') })?.filename, 'sd35')}
                        style={{ ...btnSt, background: isSd35Act ? '#100a18' : '#0c0a09', color: isSd35Act ? '#818cf8' : '#a8a29e', borderColor: isSd35Act ? '#818cf8' : '#292524', fontWeight: isSd35Act ? 700 : 400 }}>
                        <div>✧ SD 3.5</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>SD 3.5 Large</div>
                      </button>
                    )}
                    {hasSch_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => c.filename.toLowerCase().includes('schnell'))?.filename, 'fast')}
                        style={{ ...btnSt, background: isSchnellAct ? '#0a1008' : '#0c0a09', color: isSchnellAct ? '#4ade80' : '#a8a29e', borderColor: isSchnellAct ? '#4ade80' : '#292524', fontWeight: isSchnellAct ? 700 : 400 }}>
                        <div>⚡ Fast</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>FLUX Schnell</div>
                      </button>
                    )}
                  </div>
                )
              })() : (
                <select value={rebuildModelSpeed} onChange={e => setRebuildModelSpeed(e.target.value)}
                  style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 11, fontFamily: 'inherit', boxSizing: 'border-box' }}>
                  <option value="quality">Quality (FLUX dev)</option>
                  <option value="fast">Fast (FLUX schnell)</option>
                </select>
              )}
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
              <button onClick={() => setShowRebuildModal(false)} style={{ padding: '6px 16px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer', fontWeight: 600, border: '1px solid #44403c', background: '#292524', color: '#a8a29e' }}>
                Cancel
              </button>
              <button onClick={handleConfirmRebuild} disabled={rebuilding} style={{ padding: '6px 16px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer', fontWeight: 600, border: '1px solid #7c3aed', background: '#3b0764', color: '#c4b5fd', opacity: rebuilding ? 0.7 : 1 }}>
                {rebuilding ? '⏳ Starting…' : '🔄 Rebuild'}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin-slow {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
