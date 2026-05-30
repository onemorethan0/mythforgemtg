import { useEffect, useState } from 'react'

// Renders a single generation-setting field based on its schema descriptor.
// Supported types: slider, number, select, toggle, lora.

const labelStyle = { fontSize: 12, color: '#a8a29e', display: 'block', marginBottom: 4 }
const helpStyle  = { fontSize: 11, color: '#57534e', marginTop: 3, lineHeight: 1.4 }
const rowStyle   = { marginBottom: 14 }

export default function ConfigField({ field, value, onChange }) {
  // Visibility (showIf) is handled by AdvancedPanel before rendering this field.
  return (
    <div style={rowStyle}>
      {field.type !== 'toggle' && (
        <label style={labelStyle}>
          {field.label}
          {(field.type === 'slider') && (
            <span style={{ color: '#eab308', marginLeft: 8, fontFamily: 'monospace' }}>{value}</span>
          )}
        </label>
      )}

      {field.type === 'slider' && (
        <input
          type="range" min={field.min} max={field.max} step={field.step}
          value={value ?? field.default}
          onChange={e => onChange(field.key, Number(e.target.value))}
          style={{ width: '100%', accentColor: '#eab308' }}
        />
      )}

      {field.type === 'number' && (
        <input
          type="number" min={field.min} max={field.max}
          value={value ?? ''}
          onChange={e => onChange(field.key, e.target.value === '' ? null : Number(e.target.value))}
          style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #292524', borderRadius: 6, padding: '6px 8px', fontSize: 13 }}
        />
      )}

      {field.type === 'select' && (
        <select
          value={value ?? field.default}
          onChange={e => onChange(field.key, e.target.value)}
          style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #292524', borderRadius: 6, padding: '6px 8px', fontSize: 13 }}
        >
          {field.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      )}

      {field.type === 'toggle' && (
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
          <input
            type="checkbox" checked={!!value}
            onChange={e => onChange(field.key, e.target.checked)}
            style={{ accentColor: '#eab308', width: 16, height: 16 }}
          />
          <span style={{ fontSize: 12, color: '#a8a29e' }}>{field.label}</span>
        </label>
      )}

      {field.type === 'lora' && (
        <LoraPicker value={value} onChange={v => onChange(field.key, v)} />
      )}

      {field.help && <div style={helpStyle}>{field.help}</div>}
    </div>
  )
}

// LoRA multi-select with per-LoRA strength. value = null (use style preset) or
// array of { filename, model_strength }.
function LoraPicker({ value, onChange }) {
  const [installed, setInstalled] = useState(null)  // null = loading
  const [online, setOnline]       = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch('/api/comfyui/loras')
      .then(r => r.json())
      .then(d => { if (!cancelled) { setInstalled(d.loras || []); setOnline(!!d.online) } })
      .catch(() => { if (!cancelled) { setInstalled([]); setOnline(false) } })
    return () => { cancelled = true }
  }, [])

  const selected = Array.isArray(value) ? value : []
  const isSel = fn => selected.some(s => s.filename === fn)
  const strengthOf = fn => (selected.find(s => s.filename === fn)?.model_strength ?? 0.7)

  function toggle(fn) {
    let next
    if (isSel(fn)) next = selected.filter(s => s.filename !== fn)
    else next = [...selected, { filename: fn, model_strength: 0.7, clip_strength: 0.0 }]
    onChange(next.length ? next : null)
  }
  function setStrength(fn, val) {
    onChange(selected.map(s => s.filename === fn ? { ...s, model_strength: val } : s))
  }

  if (installed === null) return <div style={helpStyle}>Loading installed LoRAs…</div>
  if (!online) return <div style={helpStyle}>ComfyUI offline — can't list LoRAs. Start ComfyUI to choose.</div>
  if (installed.length === 0) return <div style={helpStyle}>No LoRAs installed.</div>

  return (
    <div style={{ border: '1px solid #292524', borderRadius: 6, padding: 8, maxHeight: 220, overflowY: 'auto' }}>
      {value === null && (
        <div style={{ ...helpStyle, marginTop: 0, marginBottom: 6, color: '#78716c' }}>
          Using the art-style default. Check a LoRA to override.
        </div>
      )}
      {installed.map(fn => (
        <div key={fn} style={{ marginBottom: 6 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <input type="checkbox" checked={isSel(fn)} onChange={() => toggle(fn)} style={{ accentColor: '#eab308' }} />
            <span style={{ fontSize: 11, color: '#d6d3d1', wordBreak: 'break-all' }}>{fn}</span>
          </label>
          {isSel(fn) && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 24, marginTop: 2 }}>
              <input type="range" min={0} max={1.2} step={0.05} value={strengthOf(fn)}
                     onChange={e => setStrength(fn, Number(e.target.value))}
                     style={{ flex: 1, accentColor: '#eab308' }} />
              <span style={{ fontSize: 11, color: '#eab308', fontFamily: 'monospace', width: 32 }}>{strengthOf(fn)}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
