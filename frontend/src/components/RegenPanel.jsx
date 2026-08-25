import { useEffect, useRef, useState } from 'react'

// ── Regen panel (modal) ────────────────────────────────────────────────────────
export default function RegenPanel({ selectedCards, onStart, onClose, defaultArtStyle, defaultModelSpeed,
                      defaultCheckpoint,
                      commanderOriginalName, savedFaceKey, savedFaceGender,
                      savedCrewKey, savedCrewGender, single = false }) {
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
        throw new Error(`Could not reach server: ${netErr.message}`, { cause: netErr })
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
                <div style={{ fontSize: 10, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>{single ? '🙂 Card face' : '👑 Commander face'}</div>
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
