import { useEffect, useRef, useState } from 'react'
import { notify } from '../utils/toast'
import { EXPORT_FORMATS } from '../utils/exportFormats'

// Export a deck's card LIST for another site or tool (the images / PDF buttons stay as they are).
// One row per format, each with Copy (to the clipboard) and Download. The formats and what they
// write are defined server-side (deck_export.py); this list only labels them.

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // clipboard API blocked (insecure context / permissions): the old way still works
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select()
    try {
      return document.execCommand('copy')
    } catch {
      return false
    } finally {
      document.body.removeChild(ta)
    }
  }
}

export default function ExportMenu({ jobId }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const box = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDown = e => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  async function copy(f) {
    setBusy(f.key)
    try {
      const r = await fetch(`/api/deck/${jobId}/export-list?format=${f.key}&download=false`)
      if (!r.ok) {
        let d = `HTTP ${r.status}`
        try { d = (await r.json()).detail || d } catch { /* keep status */ }
        notify('error', `Could not export: ${d}`)
      } else if (await copyText(await r.text())) {
        notify('success', `Copied the ${f.label} list.`)
      } else {
        notify('error', 'Could not reach the clipboard. Use Download instead.')
      }
    } catch {
      notify('error', 'Server unreachable')
    }
    setBusy('')
  }

  function download(f) {
    const a = document.createElement('a')
    a.href = `/api/deck/${jobId}/export-list?format=${f.key}`
    a.click()
  }

  const btn = { padding: '3px 9px', borderRadius: 6, fontSize: 11, fontFamily: 'inherit',
                cursor: 'pointer', border: '1px solid #44403c', background: '#1c1917', color: '#d6d3d1' }
  return (
    <div ref={box} style={{ position: 'relative', display: 'inline-block' }}>
      <button onClick={() => setOpen(o => !o)} aria-haspopup="menu" aria-expanded={open}
        title="Copy or download the card list for Moxfield, Archidekt, Arena, MTGO, a spreadsheet, or a backup"
        style={{ padding: '5px 14px', borderRadius: 8, fontFamily: 'inherit', fontSize: 12, cursor: 'pointer',
                 border: '1px solid #44403c', background: 'none', color: '#a8a29e' }}>
        Export list ▾
      </button>
      {open && (
        <div role="menu" style={{ position: 'absolute', top: '110%', left: 0, zIndex: 60, minWidth: 330,
                                  background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10,
                                  padding: 8, boxShadow: '0 8px 28px rgba(0,0,0,0.6)' }}>
          {EXPORT_FORMATS.map(f => (
            <div key={f.key} role="menuitem" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px' }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12.5, color: '#e7e5e4', fontWeight: 600 }}>{f.label}</div>
                <div style={{ fontSize: 11, color: '#78716c' }}>{f.hint}</div>
              </div>
              {f.key !== 'backup' && (
                <button style={{ ...btn, opacity: busy === f.key ? 0.6 : 1 }} disabled={!!busy}
                        onClick={() => copy(f)}>{busy === f.key ? '…' : 'Copy'}</button>
              )}
              <button style={btn} onClick={() => download(f)}>Download</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
