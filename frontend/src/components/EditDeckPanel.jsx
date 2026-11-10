import { useEffect, useMemo, useState } from 'react'

// Manual edit: cut any card from the 99, add any card. The one edit every deck site is built
// around; until now Myth Forge only let you apply an advisor suggestion. Uses the same
// /apply-swap endpoint, which enforces singleton, colour identity and the ban list and
// recomputes the deck's stats, so a manual edit is held to the same rules as an advised one.
export default function EditDeckPanel({ deck, jobId, onChanged }) {
  const zone = useMemo(() => new Set((deck?.partners || []).map(n => (n || '').toLowerCase())),
    [deck?.partners])
  const names = useMemo(() => [...new Set((deck?.deck || [])
    .map(c => c.original_name).filter(n => n && !zone.has(n.toLowerCase())))].sort(),
  [deck?.deck, zone])
  const [cut, setCut] = useState('')
  const [add, setAdd] = useState('')
  const [hints, setHints] = useState([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)        // { ok, text }
  // Change commander: cards in the 99 that could lead the deck (CR 903.3: a legendary
  // creature's FRONT face, or text saying it "can be your commander"). The server re-checks.
  const eligible = useMemo(() => [...new Set((deck?.deck || [])
    .filter(c => c.original_name && !zone.has(c.original_name.toLowerCase()))
    .filter(c => {
      const front = (c.original_type_line || c.type_line || '').split(' // ')[0].toLowerCase()
      return (front.includes('legendary') && front.includes('creature'))
        || (c.oracle_text || '').toLowerCase().includes('can be your commander')
    })
    .map(c => c.original_name))].sort(), [deck?.deck, zone])
  const [newCmd, setNewCmd] = useState('')
  const [cmdBusy, setCmdBusy] = useState(false)
  const [cmdMsg, setCmdMsg] = useState(null)  // { ok, text }

  async function switchCommander() {
    if (!newCmd || cmdBusy) return
    const old = deck?.commander?.original_name || 'the commander'
    if (!window.confirm(`Make ${newCmd} the commander? ${old} moves into the 99.`)) return
    setCmdBusy(true); setCmdMsg(null)
    try {
      const r = await fetch(`/api/deck/${jobId}/set-commander`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card: newCmd }),
      })
      if (r.ok) {
        const updated = await r.json()
        const off = updated.off_identity || []
        setCmdMsg({ ok: true, text: `${newCmd} is now the commander; ${old} is in the 99.`
          + (off.length ? ` ${off.length} card${off.length === 1 ? ' is' : 's are'} outside its colour identity: ${off.slice(0, 6).join(', ')}${off.length > 6 ? '…' : ''}.` : '')
          + ' Re-run Measure and Advise for the new list.' })
        setNewCmd('')
        onChanged?.(updated)
      } else {
        let d = `HTTP ${r.status}`
        try { d = (await r.json()).detail || d } catch { /* keep status */ }
        setCmdMsg({ ok: false, text: d })
      }
    } catch {
      setCmdMsg({ ok: false, text: 'Server unreachable' })
    }
    setCmdBusy(false)
  }

  // Scryfall typeahead (debounced); same endpoint the collection add box uses.
  useEffect(() => {
    const term = add.trim()
    if (term.length < 2) return undefined     // stale hints are hidden at render, below
    let live = true
    const t = setTimeout(() => {
      fetch(`/api/collection/suggest?q=${encodeURIComponent(term)}`)
        .then(r => r.ok ? r.json() : { suggestions: [] })
        .then(d => { if (live) setHints(d.suggestions || []) })
        .catch(() => {})
    }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [add])

  async function apply() {
    if (!cut || !add.trim() || busy) return
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(`/api/deck/${jobId}/apply-swap`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cut, add: add.trim() }),
      })
      if (r.ok) {
        const updated = await r.json()
        setMsg({ ok: true, text: `Cut ${cut}, added ${add.trim()}.` })
        setCut(''); setAdd(''); setHints([])
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

  if (!names.length) return null
  return (
    <div style={{ background: '#0c0a09', border: '1px solid #292524', borderRadius: 10, padding: 14, marginTop: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#d6d3d1', marginBottom: 8 }}>✏️ Edit deck</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={cut} onChange={e => setCut(e.target.value)} style={field} aria-label="Card to cut">
          <option value="">Cut…</option>
          {names.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <span style={{ color: '#78716c' }}>→</span>
        <input value={add} onChange={e => setAdd(e.target.value)} list={`add-hints-${jobId}`}
               placeholder="Add a card…" style={{ ...field, flex: 1, minWidth: 160 }} aria-label="Card to add" />
        <datalist id={`add-hints-${jobId}`}>{(add.trim().length >= 2 ? hints : []).map(h => <option key={h} value={h} />)}</datalist>
        <button onClick={apply} disabled={!cut || !add.trim() || busy} style={{
          padding: '7px 14px', borderRadius: 7, fontSize: 12, fontFamily: 'inherit',
          cursor: (!cut || !add.trim() || busy) ? 'default' : 'pointer',
          border: '1px solid #ca8a04', background: '#422006', color: '#fde047',
          opacity: (!cut || !add.trim() || busy) ? 0.5 : 1,
        }}>{busy ? 'Swapping…' : 'Swap'}</button>
      </div>
      <div style={{ fontSize: 11, color: '#78716c', marginTop: 6 }}>
        Checked for colour identity, singleton and the ban list. The new card shows its real art until you regenerate it.
      </div>
      {msg && <div style={{ fontSize: 12, marginTop: 6, color: msg.ok ? '#86efac' : '#f87171' }}>{msg.text}</div>}

      <div style={{ borderTop: '1px solid #292524', marginTop: 12, paddingTop: 10 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: '#d6d3d1', marginBottom: 6 }}>
          👑 Change commander
        </div>
        {zone.size > 0 ? (
          <div style={{ fontSize: 11.5, color: '#78716c' }}>
            This deck has partner commanders; switching one of a pair isn't supported yet.
          </div>
        ) : eligible.length === 0 ? (
          <div style={{ fontSize: 11.5, color: '#78716c' }}>
            No other card in the 99 can be a commander (it needs to be a legendary creature or
            say it can be your commander).
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: '#a8a29e' }}>
              {deck?.commander?.original_name} →
            </span>
            <select value={newCmd} onChange={e => setNewCmd(e.target.value)} style={field}
                    aria-label="New commander">
              <option value="">Choose a legend from the 99…</option>
              {eligible.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
            <button onClick={switchCommander} disabled={!newCmd || cmdBusy} style={{
              padding: '7px 14px', borderRadius: 7, fontSize: 12, fontFamily: 'inherit',
              cursor: (!newCmd || cmdBusy) ? 'default' : 'pointer',
              border: '1px solid #ca8a04', background: '#422006', color: '#fde047',
              opacity: (!newCmd || cmdBusy) ? 0.5 : 1,
            }}>{cmdBusy ? 'Switching…' : 'Make commander'}</button>
          </div>
        )}
        {cmdMsg && <div style={{ fontSize: 12, marginTop: 6, color: cmdMsg.ok ? '#86efac' : '#f87171' }}>{cmdMsg.text}</div>}
      </div>
    </div>
  )
}

const field = {
  padding: '7px 10px', borderRadius: 7, fontSize: 12.5, fontFamily: 'inherit',
  border: '1px solid #44403c', background: '#1c1917', color: '#e7e5e4',
}
