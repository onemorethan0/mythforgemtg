import { useState } from 'react'

// One-click legality repair (POST /api/deck/{id}/fix-legality, B21). Always a dry run first:
// the user sees exactly what goes and how many cards come in before anything is written, and
// "apply" creates a NEW deck (fixed_from this one), so the original is never touched.
export default function LegalityFix({ jobId, onFixed }) {
  const [plan, setPlan] = useState(null)
  const [partner, setPartner] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function call(apply) {
    setBusy(true); setError('')
    try {
      const r = await fetch(`/api/deck/${jobId}/fix-legality`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apply, partner: partner.trim() }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`)
      if (apply && d.new_job_id) onFixed?.(d.new_job_id)
      else setPlan(d)
    } catch (e) {
      setError(e.message || 'failed')
    }
    setBusy(false)
  }

  const btn = (primary) => ({
    padding: '5px 12px', borderRadius: 7, fontSize: 11.5, fontFamily: 'inherit',
    cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
    border: primary ? '1px solid #15803d' : '1px solid #44403c',
    background: primary ? '#052e16' : 'none', color: primary ? '#86efac' : '#d6d3d1',
  })

  if (!plan) {
    return (
      <div style={{ marginTop: 6 }}>
        <button style={btn(false)} disabled={busy} onClick={() => call(false)}>
          {busy ? 'Checking…' : '⚖️ How do I make this legal?'}
        </button>
        {error && <div style={{ fontSize: 11, color: '#f87171', marginTop: 4 }}>{error}</div>}
      </div>
    )
  }

  const reduce = Object.entries(plan.reduce || {})
  const trim = Object.entries(plan.trim || {})
  return (
    <div style={{ marginTop: 8, padding: 10, borderRadius: 8, background: '#0c0a09', border: '1px solid #292524', fontSize: 11.5, color: '#d6d3d1', lineHeight: 1.5 }}>
      {plan.partner_added && <div>Restore partner: <b>{plan.partner_added}</b></div>}
      {plan.remove.length > 0 && <div>Remove ({plan.remove.length}): {plan.remove.join(', ')}</div>}
      {reduce.length > 0 && <div>Cut extra copies: {reduce.map(([n, k]) => `${n} → ${k}`).join(', ')}</div>}
      {trim.length > 0 && <div>Trim basics: {trim.map(([n, k]) => `${k} ${n}`).join(', ')}</div>}
      {plan.refill > 0 && <div>Add {plan.refill} card{plan.refill === 1 ? '' : 's'} chosen by the builder for this commander and bracket.</div>}
      {plan.unfixable.map((u, i) => <div key={i} style={{ color: '#fbbf24' }}>{u}</div>)}
      {plan.suggest_partner && !plan.partner_added && (
        <div style={{ marginTop: 6, color: '#a8a29e' }}>
          Half this deck is outside the commander’s colours and the commander has a partner ability: an older build may have lost its partner. Name it to keep those cards:
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <input value={partner} onChange={e => setPartner(e.target.value)} placeholder="e.g. Thrasios, Triton Hero"
                   aria-label="Partner commander"
                   style={{ flex: 1, padding: '5px 8px', borderRadius: 6, fontSize: 11.5, fontFamily: 'inherit', border: '1px solid #44403c', background: '#1c1917', color: '#e7e5e4' }} />
            <button style={btn(false)} disabled={busy || !partner.trim()} onClick={() => call(false)}>Re-check</button>
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        {plan.fixable && (
          <button style={btn(true)} disabled={busy} onClick={() => call(true)}>
            {busy ? 'Working…' : 'Create a legal copy'}
          </button>
        )}
        <button style={btn(false)} disabled={busy} onClick={() => { setPlan(null); setPartner('') }}>Close</button>
      </div>
      <div style={{ color: '#78716c', marginTop: 4 }}>Your current deck is kept as it is; the fix is saved as a new deck.</div>
      {error && <div style={{ color: '#f87171', marginTop: 4 }}>{error}</div>}
    </div>
  )
}
