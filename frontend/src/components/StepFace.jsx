import { useState, useEffect, useRef, useCallback } from 'react'
import ManaCost from './ManaCost'

const MAX_COMMANDER_PHOTOS = 5
const MAX_CREW_PHOTOS      = 10

const FACE_METHOD_INFO = {
  'PuLID FLUX (high quality)': { color: '#4ade80', badge: 'PuLID',   desc: 'Best quality — face identity deeply embedded into every generation.' },
  'IP-Adapter FaceID (SDXL)':  { color: '#a3e635', badge: 'FaceID',  desc: 'Great quality face conditioning for SDXL checkpoints.' },
  'ReActor face swap':          { color: '#eab308', badge: 'ReActor', desc: 'Reliable face swap applied after generation. Works with any model.' },
  'not available':              { color: '#78716c', badge: 'None',    desc: 'No face nodes detected — see setup guide below.' },
}

// ── Shared drop-zone + thumbnail grid component ───────────────────────────────
function PhotoPicker({ photos, setPhotos, maxPhotos, inputRef, accentColor = '#eab308', primaryBadge = 'primary' }) {
  const [dragging, setDragging] = useState(false)

  function addFiles(fileList) {
    const incoming = Array.from(fileList)
      .filter(f => f.type.startsWith('image/'))
      .slice(0, maxPhotos - photos.length)
    if (!incoming.length) return
    setPhotos(prev => [...prev, ...incoming.map(f => ({ file: f, url: URL.createObjectURL(f) }))].slice(0, maxPhotos))
  }
  function removePhoto(idx) {
    setPhotos(prev => { URL.revokeObjectURL(prev[idx].url); return prev.filter((_, i) => i !== idx) })
  }
  const onDrop = useCallback(e => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }, [photos.length])

  return (
    <div>
      {photos.length < maxPhotos && (
        <div
          style={{
            border: `2px dashed ${dragging ? accentColor : '#44403c'}`,
            borderRadius: 12, padding: '28px 16px', textAlign: 'center',
            cursor: 'pointer', background: dragging ? '#1c1400' : '#0c0a09',
            transition: 'all 0.2s',
          }}
          onDrop={onDrop}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onClick={() => inputRef.current?.click()}
        >
          <div style={{ fontSize: 32, marginBottom: 8 }}>📷</div>
          <div style={{ fontSize: 13, color: '#a8a29e', marginBottom: 3 }}>
            {dragging ? 'Drop photos here' : 'Drag & drop photos here'}
          </div>
          <div style={{ fontSize: 11, color: '#57534e', marginBottom: 10 }}>
            JPG, PNG, WebP · up to {maxPhotos} photo{maxPhotos !== 1 ? 's' : ''}
          </div>
          <button
            style={{ padding: '6px 16px', background: 'none', border: '1px solid #44403c', borderRadius: 8, color: '#a8a29e', cursor: 'pointer', fontSize: 12, fontFamily: 'inherit' }}
            onClick={e => { e.stopPropagation(); inputRef.current?.click() }}
          >Browse files</button>
        </div>
      )}

      {photos.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(90px, 1fr))', gap: 8, marginTop: 12 }}>
          {photos.map((p, i) => (
            <div key={p.url} style={{ position: 'relative', aspectRatio: '1', borderRadius: 8, overflow: 'hidden', background: '#0c0a09' }}>
              <img src={p.url} alt={`Photo ${i+1}`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              {i === 0 && (
                <span style={{ position: 'absolute', bottom: 4, left: 4, fontSize: 9, padding: '2px 5px', borderRadius: 5, background: `${accentColor}88`, color: accentColor, border: `1px solid ${accentColor}44` }}>
                  {primaryBadge}
                </span>
              )}
              <button
                onClick={() => removePhoto(i)}
                style={{ position: 'absolute', top: 3, right: 3, width: 20, height: 20, borderRadius: '50%', background: '#0c0a09cc', border: '1px solid #44403c', color: '#a8a29e', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'inherit', lineHeight: 1 }}
              >×</button>
            </div>
          ))}
          {photos.length < maxPhotos && (
            <div
              onClick={() => inputRef.current?.click()}
              style={{ aspectRatio: '1', borderRadius: 8, border: '2px dashed #44403c', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 24, color: '#44403c' }}
            >+</div>
          )}
        </div>
      )}

      <input ref={inputRef} type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={e => addFiles(e.target.files)} />
    </div>
  )
}

function GenderPicker({ value, onChange, label = "Person's sex:" }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14 }}>
      <span style={{ fontSize: 12, color: '#a8a29e', flexShrink: 0 }}>{label}</span>
      <div style={{ display: 'flex', gap: 6 }}>
        {[{ key: 'female', label: '♀ Female' }, { key: 'male', label: '♂ Male' }, { key: 'either', label: '⊕ Either' }].map(({ key, label: lbl }) => (
          <button key={key} onClick={() => onChange(key)} style={{
            padding: '5px 12px', borderRadius: 8, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
            border:      value === key ? '1px solid #eab308' : '1px solid #44403c',
            background:  value === key ? '#eab30820' : 'none',
            color:       value === key ? '#eab308' : '#78716c',
          }}>{lbl}</button>
        ))}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function StepFace({ commander, faceGender, onGenderChange, crewGender, onCrewGenderChange, onNext, onSkip, onBack }) {
  const [cmdPhotos,  setCmdPhotos]  = useState([])
  const [crewPhotos, setCrewPhotos] = useState([])
  const [uploading,  setUploading]  = useState(false)
  const [error,      setError]      = useState('')
  const [faceMethod, setFaceMethod] = useState(null)
  const [comfyOffline, setComfyOffline] = useState(false)

  const cmdRef  = useRef()
  const crewRef = useRef()

  const hasAny      = cmdPhotos.length > 0 || crewPhotos.length > 0
  const methodInfo  = FACE_METHOD_INFO[faceMethod] || FACE_METHOD_INFO['not available']
  const noFaceNodes = faceMethod === 'not available' || faceMethod === null

  useEffect(() => {
    fetch('/api/face-method').then(r => r.ok ? r.json() : null).then(d => {
      if (!d) return
      if (d.comfyui_offline) setComfyOffline(true)
      if (d.face_method)     setFaceMethod(d.face_method)
    }).catch(() => {})
  }, [])

  async function uploadGroup(photos, label) {
    if (!photos.length) return null
    const form = new FormData()
    photos.forEach(p => form.append('files', p.file))
    let res
    try {
      res = await fetch('/api/upload-face', { method: 'POST', body: form })
    } catch (netErr) {
      throw new Error(`${label} upload failed — could not reach server: ${netErr.message}`)
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { const e = await res.json(); if (e.detail) detail = e.detail } catch {}
      throw new Error(`${label} upload failed: ${detail}`)
    }
    const data = await res.json()
    if (data.face_method) setFaceMethod(data.face_method)
    return data.face_key
  }

  async function handleContinue() {
    if (!hasAny) return
    setUploading(true)
    setError('')
    try {
      // Upload sequentially so errors are attributed to the right group
      const faceKey = await uploadGroup(cmdPhotos, 'Commander photos')
      const crewKey = await uploadGroup(crewPhotos, 'Crew photos')
      onNext(faceKey, faceMethod, faceGender, crewKey, crewGender)
    } catch (err) {
      setError(err.message)
      setUploading(false)
    }
  }

  return (
    <div style={{ maxWidth: 780, width: '100%', marginTop: 16 }}>

      {/* Commander chip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, background: '#1c1917', border: '1px solid #292524', borderRadius: 12, padding: '12px 18px', marginBottom: 20 }}>
        {commander.image_url
          ? <img src={commander.image_url} alt={commander.name} style={{ width: 44, height: 44, borderRadius: 6, objectFit: 'cover' }} />
          : <div style={{ width: 44, height: 44, borderRadius: 6, background: '#292524', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57534e' }}>?</div>
        }
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#f5f5f4' }}>{commander.name} <ManaCost cost={commander.mana_cost} size={14} /></div>
          <div style={{ fontSize: 11, color: '#78716c' }}>{commander.type_line}</div>
        </div>
      </div>

      {/* Two-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>

        {/* ── Commander face card ── */}
        <div style={{ background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 22 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 20 }}>👑</span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#eab308' }}>Commander Portrait</div>
              <div style={{ fontSize: 11, color: '#57534e' }}>optional</div>
            </div>
            {cmdPhotos.length > 0 && (
              <span style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#eab30820', color: '#eab308', border: '1px solid #eab30844' }}>
                {cmdPhotos.length} photo{cmdPhotos.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <p style={{ fontSize: 12, color: '#78716c', lineHeight: 1.6, marginBottom: 14, margin: '0 0 14px' }}>
            Photos of <strong style={{ color: '#a8a29e' }}>one person</strong>. Their face will appear on the commander card and similar humanoid cards.
          </p>
          <PhotoPicker photos={cmdPhotos} setPhotos={setCmdPhotos} maxPhotos={MAX_COMMANDER_PHOTOS} inputRef={cmdRef} accentColor='#eab308' primaryBadge='primary' />
          <GenderPicker value={faceGender} onChange={onGenderChange} label="Sex:" />
        </div>

        {/* ── Crew faces card ── */}
        <div style={{ background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 22 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 20 }}>👥</span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#4ade80' }}>Crew Portraits</div>
              <div style={{ fontSize: 11, color: '#57534e' }}>optional</div>
            </div>
            {crewPhotos.length > 0 && (
              <span style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#4ade8020', color: '#4ade80', border: '1px solid #4ade8044' }}>
                {crewPhotos.length} photo{crewPhotos.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <p style={{ fontSize: 12, color: '#78716c', lineHeight: 1.6, marginBottom: 14, margin: '0 0 14px' }}>
            Photos of <strong style={{ color: '#a8a29e' }}>different people</strong>. Each photo is a separate person — they're distributed round-robin across warrior, wizard, and other humanoid creature cards.
          </p>
          <PhotoPicker photos={crewPhotos} setPhotos={setCrewPhotos} maxPhotos={MAX_CREW_PHOTOS} inputRef={crewRef} accentColor='#4ade80' primaryBadge='person 1' />
          <GenderPicker value={crewGender} onChange={onCrewGenderChange} label="Sex:" />
        </div>
      </div>

      {/* Face method status */}
      {faceMethod && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '12px 16px', borderRadius: 10, border: '1px solid #292524', background: '#0c0a09', marginBottom: 14 }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: methodInfo.color, marginTop: 4, flexShrink: 0 }} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f5f5f4', marginBottom: 2 }}>
              Face engine: {faceMethod}
              <span style={{ marginLeft: 8, fontSize: 10, padding: '2px 7px', borderRadius: 10, background: `${methodInfo.color}22`, color: methodInfo.color, border: `1px solid ${methodInfo.color}44` }}>
                {methodInfo.badge}
              </span>
            </div>
            <div style={{ fontSize: 12, color: '#78716c' }}>{methodInfo.desc}</div>
          </div>
        </div>
      )}

      {/* ComfyUI offline notice */}
      {noFaceNodes && comfyOffline && (
        <div style={{ padding: '12px 16px', borderRadius: 10, background: '#0a0800', border: '1px solid #44403c33', marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#78716c', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>⚠ ComfyUI is not running</div>
          <div style={{ fontSize: 12, color: '#57534e', lineHeight: 1.6 }}>
            Face reference requires ComfyUI on port 8188. You can still upload photos now — they'll be used once ComfyUI is running.
          </div>
        </div>
      )}

      {/* Setup guide */}
      {noFaceNodes && !comfyOffline && faceMethod !== null && (
        <div style={{ padding: '14px 16px', borderRadius: 10, background: '#0a0800', border: '1px solid #44403c33', marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#78716c', marginBottom: 8, letterSpacing: '0.1em', textTransform: 'uppercase' }}>Install a face engine for best results</div>
          <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 4 }}><strong>Option 1 — PuLID (recommended for FLUX):</strong></div>
          <div style={{ fontSize: 12, color: '#57534e', lineHeight: 1.6, marginBottom: 2 }}>1. ComfyUI Manager → Install Custom Nodes → <span style={{ fontFamily: 'monospace', color: '#a8a29e', background: '#1c1917', padding: '1px 4px', borderRadius: 3 }}>ComfyUI_PuLID_Flux</span></div>
          <div style={{ fontSize: 12, color: '#57534e', lineHeight: 1.6, marginBottom: 8 }}>2. Download <span style={{ fontFamily: 'monospace', color: '#a8a29e', background: '#1c1917', padding: '1px 4px', borderRadius: 3 }}>pulid_flux_v0.9.1.safetensors</span> → <span style={{ fontFamily: 'monospace', color: '#a8a29e', background: '#1c1917', padding: '1px 4px', borderRadius: 3 }}>ComfyUI/models/pulid/</span></div>
          <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 4 }}><strong>Option 2 — ReActor (easiest, any model):</strong></div>
          <div style={{ fontSize: 12, color: '#57534e', lineHeight: 1.6 }}>ComfyUI Manager → Install Custom Nodes → <span style={{ fontFamily: 'monospace', color: '#a8a29e', background: '#1c1917', padding: '1px 4px', borderRadius: 3 }}>ComfyUI-ReActor</span> → restart ComfyUI</div>
        </div>
      )}

      {/* Tips */}
      {hasAny && (
        <div style={{ padding: '10px 14px', borderRadius: 8, background: '#1c1400', border: '1px solid #eab30833', marginBottom: 14 }}>
          <div style={{ fontSize: 12, color: '#a16207', lineHeight: 1.6 }}>
            💡 <strong>Best results:</strong> Clear, front-facing photos with good lighting. Multiple photos of the same person improve consistency. Each crew photo = one person who'll appear on creature cards.
          </div>
        </div>
      )}

      {error && (
        <div style={{ padding: '10px 14px', borderRadius: 8, background: '#1a0505', border: '1px solid #ef444433', fontSize: 13, color: '#ef4444', marginBottom: 14 }}>
          {error}
        </div>
      )}

      {/* Footer */}
      <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
        <button style={{ padding: '10px 22px', background: 'none', border: '1px solid #44403c', borderRadius: 10, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit' }} onClick={onBack} disabled={uploading}>
          ← Back
        </button>
        <button style={{ padding: '10px 22px', background: 'none', border: '1px solid #44403c', borderRadius: 10, color: '#78716c', cursor: 'pointer', fontFamily: 'inherit' }} onClick={() => onSkip()} disabled={uploading}>
          Skip (no photos)
        </button>
        <button
          style={{ padding: '10px 28px', background: hasAny && !uploading ? 'linear-gradient(180deg,#eab308,#a16207)' : '#292524', border: 'none', borderRadius: 10, color: hasAny && !uploading ? '#0c0a09' : '#57534e', fontWeight: 700, cursor: hasAny && !uploading ? 'pointer' : 'not-allowed', fontFamily: 'inherit', fontSize: 14, opacity: uploading ? 0.6 : 1 }}
          disabled={!hasAny || uploading}
          onClick={handleContinue}
        >
          {uploading ? 'Uploading…' : hasAny
            ? `Use Photos (${[cmdPhotos.length && `👑 ${cmdPhotos.length}`, crewPhotos.length && `👥 ${crewPhotos.length}`].filter(Boolean).join(' + ')}) →`
            : 'Continue →'}
        </button>
      </div>
    </div>
  )
}
