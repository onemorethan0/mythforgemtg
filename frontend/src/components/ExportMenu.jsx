import { useState } from 'react'
import { notify } from '../utils/toast'
import { EXPORT_FORMATS } from '../utils/exportFormats'
import Menu from './ui/Menu'
import Button from './ui/Button'

// Export a deck's card LIST for another site or tool (the images / PDF buttons stay as they are).
// One row per format, each with Copy (to the clipboard) and Download. The formats and what they
// write are defined server-side (deck_export.py); utils/exportFormats.js only labels them.

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
  const [busy, setBusy] = useState('')

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

  return (
    <Menu label="Export list ▾"
          title="Copy or download the card list for Moxfield, Archidekt, Arena, MTGO, a spreadsheet, or a backup">
      {EXPORT_FORMATS.map(f => (
        <div key={f.key} role="menuitem" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12.5, color: 'var(--text)', fontWeight: 600 }}>{f.label}</div>
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)' }}>{f.hint}</div>
          </div>
          {f.key !== 'backup' && (
            <Button size="xs" disabled={!!busy} onClick={() => copy(f)}>{busy === f.key ? '…' : 'Copy'}</Button>
          )}
          <Button size="xs" onClick={() => download(f)}>Download</Button>
        </div>
      ))}
    </Menu>
  )
}
