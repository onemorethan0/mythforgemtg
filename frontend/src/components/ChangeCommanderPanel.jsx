import { useMemo, useState } from 'react'
import Button from './ui/Button'

// Change commander: cards in the 99 that could lead the deck (CR 903.3: a legendary creature's FRONT
// face, or text saying it "can be your commander"). The server re-checks. This is what is left of the
// old Edit deck panel: adding, removing and swapping moved to the bar above the list (AddCardBar).
export default function ChangeCommanderPanel({ deck, jobId, onChanged }) {
  const zone = useMemo(() => new Set((deck?.partners || []).map(n => (n || '').toLowerCase())),
    [deck?.partners])
  const eligible = useMemo(() => [...new Set((deck?.deck || [])
    .filter(c => c.original_name && !zone.has(c.original_name.toLowerCase()))
    .filter(c => {
      const front = (c.original_type_line || c.type_line || '').split(' // ')[0].toLowerCase()
      return (front.includes('legendary') && front.includes('creature'))
        || (c.oracle_text || '').toLowerCase().includes('can be your commander')
    })
    .map(c => c.original_name))].sort(), [deck?.deck, zone])
  const [newCmd, setNewCmd] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)        // { ok, text }

  async function switchCommander() {
    if (!newCmd || busy) return
    const old = deck?.commander?.original_name || 'the commander'
    if (!window.confirm(`Make ${newCmd} the commander? ${old} moves into the 99.`)) return
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`/api/deck/${jobId}/set-commander`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card: newCmd }),
      })
      if (r.ok) {
        const updated = await r.json()
        const off = updated.off_identity || []
        setMsg({ ok: true, text: `${newCmd} is now the commander; ${old} is in the 99.`
          + (off.length ? ` ${off.length} card${off.length === 1 ? ' is' : 's are'} outside its colour identity: ${off.slice(0, 6).join(', ')}${off.length > 6 ? '…' : ''}.` : '')
          + ' Re-run Measure and Advise for the new list.' })
        setNewCmd('')
        onChanged?.(updated)
      } else {
        let d = `HTTP ${r.status}`
        try { d = (await r.json()).detail || d } catch { /* keep status */ }
        setMsg({ ok: false, text: d })
      }
    } catch {
      setMsg({ ok: false, text: 'Server unreachable' })
    }
    setBusy(false)
  }

  if (!deck?.deck?.length) return null
  return (
    <div style={{ background: 'var(--surface-0)', border: '1px solid var(--surface-2)', borderRadius: 'var(--radius-lg)', padding: 14 }}>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: '#d6d3d1', marginBottom: 6 }}>👑 Change commander</div>
      {zone.size > 0 ? (
        <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
          This deck has partner commanders; switching one of a pair isn't supported yet.
        </div>
      ) : eligible.length === 0 ? (
        <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
          No other card in the 99 can be a commander (it needs to be a legendary creature or say it can be
          your commander).
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{deck?.commander?.original_name} →</span>
          <select value={newCmd} onChange={e => setNewCmd(e.target.value)} aria-label="New commander"
                  style={{ padding: '7px 10px', borderRadius: 7, fontSize: 12.5, fontFamily: 'inherit',
                           border: '1px solid var(--border)', background: 'var(--surface-1)', color: '#e7e5e4' }}>
            <option value="">Choose a legend from the 99…</option>
            {eligible.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
          <Button variant="primary" onClick={switchCommander} disabled={!newCmd || busy}>
            {busy ? 'Switching…' : 'Make commander'}
          </Button>
        </div>
      )}
      {msg && <div style={{ fontSize: 12, marginTop: 6, color: msg.ok ? 'var(--ok)' : '#f87171' }}>{msg.text}</div>}
    </div>
  )
}
