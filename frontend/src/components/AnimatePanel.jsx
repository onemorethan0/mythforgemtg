import { useEffect, useState } from 'react'

// ── Animate panel (modal) ───────────────────────────────────────────────────
export default function AnimatePanel({ selectedCards, presets, foilStyles, formats, loopStyles, caps, health, onStart, onClose }) {
  const i2vOk = !!health?.ok
  const [effect, setEffect]   = useState(i2vOk ? 'motion' : 'foil')
  const [preset, setPreset]   = useState(presets?.[0]?.key || 'subtle')
  const [foilStyle, setFoilStyle] = useState(foilStyles?.[0]?.key || 'holo')
  const [fmt, setFmt]         = useState('mp4')
  // No `loop` state: the payload's `loop` flag is derived from loopStyle below
  // (`loop: loopStyle !== 'off'`), which is what the <select> actually writes.
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
