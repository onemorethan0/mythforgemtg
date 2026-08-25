import { useState, useRef, useEffect } from 'react'

// Deck Mentor (docs/SPEC_deck_mentor.md, Phase 2) — ask a free-form question about this
// deck, a card, or a rule. Every reply from the engine already passed the claim-budget
// gate (mentor.gate) before it left the server; `gated: false` on a message means the
// gate rejected every drafted answer and this is the model's honest "I'm not sure"
// fallback, not a claim that slipped past a check. Rendered visibly differently on
// purpose — the whole point of the gate is that a user must never have to guess which
// answers were verified, so an unverified one cannot be allowed to look equally
// confident as a verified one.

const boxStyle = {
  marginTop: 8, borderRadius: 10, border: '1px solid #292524', background: '#0c0a09',
  overflow: 'hidden',
}

export default function MentorChatPanel({ jobId }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])   // [{role, content, gated}]
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [errMsg, setErrMsg] = useState('')
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, busy])

  async function ask(e) {
    e?.preventDefault?.()
    const question = input.trim()
    if (!question || busy) return
    setBusy(true); setErrMsg('')
    const history = messages.map(({ role, content }) => ({ role, content }))
    const next = [...messages, { role: 'user', content: question }]
    setMessages(next)
    setInput('')
    try {
      const r = await fetch(`/api/deck/${jobId}/mentor`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, history }),
      })
      if (r.ok) {
        const body = await r.json()
        setMessages(m => [...m, { role: 'assistant', content: body.reply, gated: body.gated }])
      } else {
        let d = `HTTP ${r.status}`
        try { d = (await r.json()).detail || d } catch { /* keep the status */ }
        setErrMsg(d)
      }
    } catch {
      setErrMsg('Strength API unreachable — is Myth Forge running via manage.bat?')
    }
    setBusy(false)
  }

  return (
    <div style={boxStyle}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', background: 'transparent', border: 'none', cursor: 'pointer',
          color: '#f5f5f4', fontSize: 13, fontWeight: 600, fontFamily: 'inherit',
        }}
      >
        <span>🧙 Ask the Mentor</span>
        <span style={{ color: '#78716c', fontSize: 11 }}>{open ? '▲ hide' : '▼ ask a question about this deck'}</span>
      </button>

      {open && (
        <div style={{ padding: '0 14px 14px' }}>
          <div style={{ color: '#78716c', fontSize: 11, marginBottom: 8, lineHeight: 1.5 }}>
            Ask about your curve, a specific card, a swap, or a rule. Every answer is checked
            against real tool lookups before it's shown — an answer marked{' '}
            <span style={{ color: '#eab308' }}>⚠ unverified</span> means the mentor couldn't
            confirm it precisely enough and is telling you so rather than guessing.
          </div>

          {messages.length > 0 && (
            <div
              ref={scrollRef}
              style={{
                maxHeight: 320, overflowY: 'auto', display: 'flex', flexDirection: 'column',
                gap: 8, marginBottom: 10, paddingRight: 2,
              }}
            >
              {messages.map((m, i) => (
                <div
                  key={i}
                  style={{
                    alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '88%',
                    padding: '8px 12px', borderRadius: 10, fontSize: 13, lineHeight: 1.5,
                    background: m.role === 'user' ? '#1c1917'
                      : m.gated === false ? '#1c1408' : '#0c1f12',
                    border: `1px solid ${m.role === 'user' ? '#292524'
                      : m.gated === false ? '#a16207' : '#166534'}`,
                    color: '#f5f5f4', whiteSpace: 'pre-wrap',
                  }}
                >
                  {m.role === 'assistant' && m.gated === false && (
                    <div style={{ color: '#eab308', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                      ⚠ unverified — couldn't confirm this precisely
                    </div>
                  )}
                  {m.content}
                </div>
              ))}
              {busy && (
                <div style={{
                  alignSelf: 'flex-start', color: '#78716c', fontSize: 12, padding: '4px 12px',
                }}>
                  thinking…
                </div>
              )}
            </div>
          )}

          {errMsg && (
            <div style={{
              marginBottom: 10, padding: '9px 12px', borderRadius: 8,
              background: '#1f0c0c', border: '1px solid #7f1d1d', color: '#fca5a5', fontSize: 12,
            }}>
              {errMsg}
            </div>
          )}

          <form onSubmit={ask} style={{ display: 'flex', gap: 8 }}>
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="e.g. Why does my curve feel bad?"
              aria-label="Ask the Deck Mentor"
              maxLength={2000}
              style={{
                flex: 1, padding: '8px 12px', borderRadius: 8,
                border: '1px solid #292524', background: '#0c0a09', color: '#f5f5f4',
                fontSize: 13, fontFamily: 'inherit', outline: 'none',
              }}
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              style={{
                padding: '8px 16px', borderRadius: 8, border: '1px solid #a16207',
                background: '#1c1408', color: '#eab308', fontWeight: 600, fontSize: 13,
                cursor: busy || !input.trim() ? 'default' : 'pointer', fontFamily: 'inherit',
                opacity: busy || !input.trim() ? 0.5 : 1,
              }}
            >
              {busy ? '…' : 'Ask'}
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
