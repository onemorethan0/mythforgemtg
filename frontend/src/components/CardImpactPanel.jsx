import { useState } from 'react'
import CardHover from './CardHover'

// "Would this card help my deck?" — ask about ONE named card and get a measured answer.
//
// The inverse of AdvisePanel: that proposes cards you own, this answers the question a
// player actually asks mid-conversation. Legality is judged before anything is simulated,
// so an off-colour or banned card comes back as a refusal with the reason rather than a
// power score for a card that cannot go in the deck.
//
// Deltas smaller than an axis's own seed-to-seed spread are reported by the engine as NOT
// meaningful; those render greyed with a "within noise" note instead of as a win or a loss,
// because presenting a coin flip as an improvement is how this feature would lose trust.

const VERDICT = {
  positive: { color: '#4ade80', bg: '#0c1f12', border: '#166534', icon: '▲', label: 'Helps' },
  negative: { color: '#f87171', bg: '#1f0c0c', border: '#7f1d1d', icon: '▼', label: 'Hurts' },
  neutral:  { color: '#a8a29e', bg: '#1c1917', border: '#292524', icon: '=', label: 'No change' },
  illegal:  { color: '#fbbf24', bg: '#1c1408', border: '#a16207', icon: '⚠', label: 'Not legal' },
}

export default function CardImpactPanel({ jobId }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')

  async function ask(e) {
    e?.preventDefault?.()
    const card = name.trim()
    if (!card || busy) return
    setBusy(true); setErrMsg(''); setResult(null)
    try {
      const r = await fetch(`/api/deck/${jobId}/card-impact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card }),
      })
      if (r.ok) {
        setResult(await r.json())
      } else {
        // Show the server's detail — for a misspelling it names the card and says to check
        // the spelling, which is far more use than "request failed".
        let d = `HTTP ${r.status}`
        try { d = (await r.json()).detail || d } catch { /* keep the status */ }
        setErrMsg(d)
      }
    } catch {
      setErrMsg('Strength API unreachable — is Myth Forge running via manage.bat?')
    }
    setBusy(false)
  }

  const v = result ? (VERDICT[result.verdict] || VERDICT.neutral) : null

  return (
    <div style={{ marginTop: 8 }}>
      <form onSubmit={ask} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Card name — e.g. Cultivate"
          aria-label="Card to evaluate against this deck"
          maxLength={200}
          style={{
            flex: '1 1 220px', minWidth: 180, padding: '7px 12px', borderRadius: 8,
            border: '1px solid #292524', background: '#0c0a09', color: '#f5f5f4',
            fontSize: 13, fontFamily: 'inherit', outline: 'none',
          }}
        />
        <button
          type="submit"
          disabled={busy || !name.trim()}
          title="Swap this card into the deck and re-simulate the whole Power Profile"
          style={{
            padding: '7px 16px', borderRadius: 8, border: '1px solid #a16207',
            background: '#1c1408', color: '#eab308', fontWeight: 600, fontSize: 13,
            cursor: busy || !name.trim() ? 'default' : 'pointer', fontFamily: 'inherit',
            opacity: busy || !name.trim() ? 0.5 : 1,
          }}
        >
          {busy ? '⏳ Measuring…' : '⚖ Would this help?'}
        </button>
        {busy && (
          <span style={{ fontSize: 11, color: '#78716c' }}>
            re-simulating the deck with and without it (~10-30s)
          </span>
        )}
      </form>

      {errMsg && (
        <div style={{
          marginTop: 10, padding: '9px 12px', borderRadius: 8,
          background: '#1f0c0c', border: '1px solid #7f1d1d', color: '#fca5a5', fontSize: 12,
        }}>
          {errMsg}
        </div>
      )}

      {result && v && (
        <div style={{
          marginTop: 10, padding: '12px 14px', borderRadius: 10,
          background: v.bg, border: `1px solid ${v.border}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ color: v.color, fontWeight: 700, fontSize: 13 }}>
              {v.icon} {v.label}
            </span>
            <span style={{ color: '#f5f5f4', fontSize: 13 }}>
              <CardHover name={result.card}>{result.card}</CardHover>
            </span>
          </div>

          <div style={{ marginTop: 6, color: '#d6d3d1', fontSize: 13, lineHeight: 1.5 }}>
            {result.headline}
          </div>

          {!!result.reasons?.length && (
            <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: '#a8a29e', fontSize: 12, lineHeight: 1.6 }}>
              {result.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}

          {/* Axis table only when something was actually simulated — an illegal card has none. */}
          {!!result.axes?.length && (
            <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {result.axes.map(a => {
                const up = a.delta > 0
                const dim = !a.meaningful
                return (
                  <span
                    key={a.axis}
                    title={dim
                      ? `Moved ${a.delta >= 0 ? '+' : ''}${a.delta}, inside this axis's ±${a.noise_floor} run-to-run spread — not a real change`
                      : `${a.before} → ${a.after}`}
                    style={{
                      fontSize: 11, padding: '3px 9px', borderRadius: 20,
                      background: '#0c0a09',
                      border: `1px solid ${dim ? '#292524' : up ? '#166534' : '#7f1d1d'}`,
                      color: dim ? '#57534e' : up ? '#4ade80' : '#f87171',
                    }}
                  >
                    {a.label} {a.delta >= 0 ? '+' : ''}{a.delta}
                    {dim && <span style={{ color: '#44403c' }}> · within noise</span>}
                  </span>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
