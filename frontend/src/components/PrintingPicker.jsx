import { useEffect, useMemo, useRef, useState } from 'react'
import CardFace, { SetChip } from './CardFace'
import {
  availableFinishes, priceFor, ownedTotal, releaseYear, isCurrentPrint,
  filterPrintings, sortPrintings,
} from '../utils/printings'

// Visual printing picker. Props: { name, row|null, mode: 'change'|'add', onDone(response), onClose }.
//   change: a finish button PATCHes the row (by row_id) to that exact print + finish.
//   add:    a finish button POSTs one more copy of that print + finish.
// onDone(response) gets the server's collection summary on success, or null when the
// collection changed under us (409) so the parent reloads. A 400 stays inline.

const c = {
  gold:   '#eab308',
  green:  '#4ade80',
  dim:    '#a8a29e',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
  err:    '#f87171',
}

const SORTS = [['newest', 'Newest'], ['cheapest', 'Cheapest'], ['oldest', 'Oldest']]
const FINISH_LABEL = { nonfoil: 'Nonfoil', foil: 'Foil', etched: 'Etched' }

const money = n => `$${n.toFixed(2)}`
const pill = extra => ({
  padding: '3px 10px', borderRadius: 6, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer',
  background: c.card, border: `1px solid ${c.border}`, color: c.dim, ...extra,
})

export default function PrintingPicker({ name, row, mode = 'change', onDone, onClose }) {
  const [printings, setPrintings] = useState([])
  const [loading, setLoading]     = useState(true)
  const [loadErr, setLoadErr]     = useState('')
  const [filter, setFilter]       = useState('')
  const [sort, setSort]           = useState('newest')
  const [ownedOnly, setOwnedOnly] = useState(false)
  const [busy, setBusy]           = useState(false)
  const [error, setError]         = useState('')
  const [reloading, setReloading] = useState(false)
  const [preview, setPreview]     = useState({})   // print id -> finish shown on its thumbnail
  const dialogRef = useRef(null)
  const filterRef = useRef(null)
  const closeRef  = useRef(onClose)
  const doneRef   = useRef(onDone)
  useEffect(() => { closeRef.current = onClose; doneRef.current = onDone })

  const change = mode === 'change' && !!row

  useEffect(() => {
    let live = true
    fetch(`/api/collection/printings?name=${encodeURIComponent(name)}`)
      .then(async r => {
        const d = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(d.detail || 'Could not load printings.')
        return d
      })
      .then(d => { if (live) setPrintings(d.printings || []) })
      .catch(e => { if (live) setLoadErr(String(e.message || e)) })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [name])

  // Focus the filter on open and hand focus back to whatever opened us on close; Escape
  // closes; Tab stays inside the dialog.
  useEffect(() => {
    const opener = document.activeElement
    filterRef.current && filterRef.current.focus()
    const onKey = e => {
      if (e.key === 'Escape') { e.stopPropagation(); closeRef.current && closeRef.current(); return }
      if (e.key !== 'Tab' || !dialogRef.current) return
      const f = dialogRef.current.querySelectorAll('button:not([disabled]), input, [tabindex="0"]')
      if (!f.length) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      if (opener && typeof opener.focus === 'function' && document.contains(opener)) opener.focus()
    }
  }, [])

  const shown = useMemo(
    () => sortPrintings(filterPrintings(printings, filter, ownedOnly), sort),
    [printings, filter, ownedOnly, sort])

  const pick = async (p, finish) => {
    if (busy || reloading) return
    setBusy(true); setError('')
    try {
      const body = { set_code: p.set, cn: p.cn, finish, scryfall_id: p.id }
      let res
      if (change) {
        res = await fetch('/api/collection/printing', {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, row_id: row.row_id }),
        })
      } else {
        res = await fetch('/api/collection/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, name, count: 1 }),
        })
      }
      const d = await res.json().catch(() => ({}))
      if (res.status === 409) {
        // The file changed under us: nothing was written. Say so, then let the parent reload.
        setReloading(true); setError('Collection changed — reloading')
        setTimeout(() => doneRef.current && doneRef.current(null), 900)
        return
      }
      if (!res.ok) { setError(d.detail || `Request failed (${res.status})`); setBusy(false); return }
      doneRef.current && doneRef.current(d)
    } catch (e) {
      setError(String(e.message || e)); setBusy(false)
    }
  }

  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.72)',
               display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={`Choose a printing of ${name}`}
        onClick={e => e.stopPropagation()}
        style={{ background: c.panel, border: `1px solid ${c.border}`, borderRadius: 12,
                 padding: 16, maxWidth: 860, width: '100%', maxHeight: '86vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <h2 style={{ fontSize: 16, color: c.gold, margin: 0 }}>
            {change ? 'Change printing' : 'Add a printing'}
          </h2>
          <span style={{ fontSize: 13, color: '#f5f5f4' }}>{name}</span>
          <button onClick={onClose} style={pill({ marginLeft: 'auto' })}>Close</button>
        </div>
        <p style={{ fontSize: 12, color: c.faint, margin: '0 0 10px' }}>
          {change
            ? `Pick a finish on a printing to move this row there; your count of ${row.count} is kept.`
            : 'Pick a finish on a printing to add one copy of it.'}
        </p>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
          <input ref={filterRef} value={filter} onChange={e => setFilter(e.target.value)}
            placeholder="Filter by set code or name" aria-label="Filter printings"
            style={{ flex: '1 1 180px', minWidth: 140, padding: '5px 10px', borderRadius: 6,
                     background: c.card, border: `1px solid ${c.border}`, color: '#f5f5f4',
                     fontFamily: 'inherit', fontSize: 12.5 }} />
          <div role="group" aria-label="Sort" style={{ display: 'flex', gap: 4 }}>
            {SORTS.map(([k, label]) => (
              <button key={k} onClick={() => setSort(k)} aria-pressed={sort === k}
                style={pill(sort === k ? { color: c.gold, borderColor: c.gold } : {})}>{label}</button>
            ))}
          </div>
          <button onClick={() => setOwnedOnly(v => !v)} aria-pressed={ownedOnly}
            style={pill(ownedOnly ? { color: c.gold, borderColor: c.gold } : {})}>Owned only</button>
        </div>

        {error && (
          <div role="alert" style={{ fontSize: 12.5, color: reloading ? c.gold : c.err, marginBottom: 10 }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ color: c.faint, fontSize: 13, padding: 20, textAlign: 'center' }}>Loading printings…</div>
        ) : loadErr ? (
          <div style={{ color: c.err, fontSize: 13, padding: 20, textAlign: 'center' }}>{loadErr}</div>
        ) : shown.length === 0 ? (
          <div style={{ color: c.faint, fontSize: 13, padding: 20, textAlign: 'center' }}>
            {printings.length === 0 ? 'No printings found for this card.' : 'No printings match.'}
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 10,
                        gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
            {shown.map(p => {
              const isCur = change && isCurrentPrint(p, row)
              const owned = ownedTotal(p)
              const tags = (p.treatments || []).filter(Boolean)
              const shownFinish = preview[p.id] || (isCur ? row.finish : null) || 'nonfoil'
              return (
                <div key={p.id || `${p.set}|${p.cn}`}
                  style={{ padding: 6, borderRadius: 8, background: isCur ? '#1c1410' : c.card,
                           border: `1px solid ${isCur ? c.gold : c.border}`,
                           boxShadow: isCur ? `0 0 0 1px ${c.gold}` : 'none' }}>
                  <div style={{ position: 'relative', aspectRatio: '488 / 680', borderRadius: 5,
                                overflow: 'hidden' }}>
                    <CardFace row={{ name, image: p.image, art_crop: p.art_crop, finish: shownFinish }} />
                    {owned > 0 && (
                      <span title={`You own ${owned} of this printing`}
                        style={{ position: 'absolute', left: 6, top: 6, zIndex: 2, padding: '1px 6px',
                                 borderRadius: 6, fontSize: 10.5, fontWeight: 700, color: c.gold,
                                 background: 'rgba(0,0,0,0.82)', border: `1px solid ${c.border}` }}>
                        owned ×{owned}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 5, flexWrap: 'wrap' }}>
                    <SetChip set={p.set} cn={p.cn} rarity={p.rarity} setName={p.set_name} />
                    <span style={{ fontSize: 10.5, color: c.faint }}>#{p.cn}</span>
                    {releaseYear(p) && <span style={{ fontSize: 10.5, color: c.faint }}>{releaseYear(p)}</span>}
                    {isCur && <span style={{ fontSize: 10, color: c.gold, marginLeft: 'auto' }}>current</span>}
                  </div>
                  {tags.length > 0 && (
                    <div style={{ fontSize: 10, color: c.dim, marginTop: 2, lineHeight: '13px' }}>
                      {tags.join(' · ')}
                    </div>
                  )}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 6 }}>
                    {availableFinishes(p).map(f => {
                      const price = priceFor(p, f)
                      const curFinish = isCur && (row.finish || 'nonfoil') === f
                      return (
                        <button key={f} disabled={busy || reloading}
                          onClick={() => pick(p, f)}
                          onMouseEnter={() => setPreview(s => ({ ...s, [p.id]: f }))}
                          onFocus={() => setPreview(s => ({ ...s, [p.id]: f }))}
                          aria-label={`${FINISH_LABEL[f]} ${p.set} ${p.cn}, ${price == null ? 'no price' : money(price)}${curFinish ? ', current' : ''}`}
                          style={{ display: 'flex', justifyContent: 'space-between', gap: 6,
                                   padding: '3px 7px', borderRadius: 6, fontSize: 11.5,
                                   fontFamily: 'inherit', cursor: busy ? 'wait' : 'pointer',
                                   background: curFinish ? '#2a1f0a' : c.panel,
                                   color: curFinish ? c.gold : c.dim,
                                   border: `1px solid ${curFinish ? c.gold : c.border}`,
                                   boxShadow: curFinish ? `0 0 0 1px ${c.gold}` : 'none' }}>
                          <span>{FINISH_LABEL[f]}</span>
                          <span style={{ color: price == null ? c.faint : c.green,
                                         fontVariantNumeric: 'tabular-nums' }}>
                            {price == null ? '—' : money(price)}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
