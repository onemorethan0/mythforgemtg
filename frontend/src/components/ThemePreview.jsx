import { useState } from 'react'

// "Preview the creative direction" — a cheap, pre-build look at how the app will
// interpret the user's deck idea. Calls POST /api/deck/theme-preview, which builds
// the world bible (must-include motifs + invented signature details + palette) and
// themes a 3-card sample, so the user can iterate on their inputs before committing
// to a full ~30-minute build. The must-include chips double as the faithfulness
// contract: ✓ = the motif shows up in the sample art, ⚠ = not yet (try rephrasing).
export default function ThemePreview({ commanderName, themeSpec, artStyle, creativity, commanderPrompt, llmModel }) {
  const [loading, setLoading] = useState(false)
  const [data, setData]       = useState(null)
  const [error, setError]     = useState('')

  const hasSetting = !!(themeSpec && (themeSpec.setting || '').trim())

  async function run() {
    setLoading(true); setError(''); setData(null)
    try {
      const res = await fetch('/api/deck/theme-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          commander_name:   commanderName || '',
          theme_spec:       themeSpec || {},
          art_style:        artStyle || 'mtg_fantasy',
          creativity:       creativity || 'balanced',
          commander_prompt: commanderPrompt || '',
          llm_model:        llmModel || null,
        }),
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.detail || `Preview failed (${res.status})`)
      setData(body)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }

  const wb = data?.world_bible
  const cov = data?.coverage || {}

  return (
    <div style={{ marginTop: 14 }}>
      <button
        onClick={run}
        disabled={loading || !hasSetting}
        title={hasSetting ? '' : 'Describe a Setting first'}
        style={{
          fontSize: 13, padding: '9px 16px', borderRadius: 10, cursor: (loading || !hasSetting) ? 'not-allowed' : 'pointer',
          background: (loading || !hasSetting) ? '#1c1917' : 'linear-gradient(180deg,#7c3aed,#5b21b6)',
          border: '1px solid ' + ((loading || !hasSetting) ? '#292524' : '#8b5cf6'),
          color: (loading || !hasSetting) ? '#57534e' : '#f5f5f4', fontFamily: 'inherit', fontWeight: 600,
          display: 'flex', alignItems: 'center', gap: 8,
        }}
      >
        <span>🔮</span> {loading ? 'Imagining your world…' : data ? 'Refresh preview' : 'Preview creative direction'}
      </button>

      {error && (
        <div style={{ marginTop: 10, padding: '10px 14px', background: '#1f0a0a', border: '1px solid #7f1d1d', borderRadius: 10, fontSize: 12, color: '#fca5a5' }}>
          {error}
        </div>
      )}

      {wb && (
        <div style={{ marginTop: 12, padding: 16, background: '#0c0a09', border: '1px solid #3b2f63', borderRadius: 12 }}>
          {/* World sentence */}
          <div style={{ fontSize: 11, fontWeight: 700, color: '#a78bfa', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
            Your world
          </div>
          <div style={{ fontSize: 13, color: '#e7e5e4', lineHeight: 1.55, marginBottom: 14 }}>{wb.world}</div>

          {/* Must-include motifs with coverage */}
          {wb.must_include?.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#a8a29e', marginBottom: 6 }}>
                Promised motifs <span style={{ color: '#57534e', fontWeight: 400 }}>— what you asked for (✓ appears in the sample art, ⚠ not yet)</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {wb.must_include.map(m => {
                  const ok = (cov[m] || 0) > 0
                  return (
                    <span key={m} style={{
                      fontSize: 12, padding: '3px 10px', borderRadius: 20,
                      background: ok ? '#0a1f12' : '#241803',
                      border: '1px solid ' + (ok ? '#16532455' : '#854d0e55'),
                      color: ok ? '#4ade80' : '#eab308',
                    }}>
                      {ok ? '✓' : '⚠'} {m}
                    </span>
                  )
                })}
              </div>
            </div>
          )}

          {/* Invented signature details — the creative "colouring" */}
          {wb.signature_details?.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#a8a29e', marginBottom: 6 }}>
                Invented for you <span style={{ color: '#57534e', fontWeight: 400 }}>— creative detail added to colour your idea</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {wb.signature_details.map(s => (
                  <span key={s} style={{ fontSize: 12, padding: '3px 10px', borderRadius: 20, background: '#150f24', border: '1px solid #4c1d9555', color: '#c4b5fd' }}>
                    + {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Palette */}
          {wb.palette && (
            <div style={{ marginBottom: 14, fontSize: 12, color: '#78716c' }}>
              <span style={{ color: '#a8a29e', fontWeight: 700 }}>Palette: </span>{wb.palette}
            </div>
          )}

          {/* Sample themed cards */}
          {data.samples?.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#a8a29e', marginBottom: 6 }}>
                Sample cards <span style={{ color: '#57534e', fontWeight: 400 }}>— a taste of how your deck will read</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {data.samples.map(s => (
                  <div key={s.original} style={{ padding: '8px 12px', background: '#1c1917', border: '1px solid #292524', borderRadius: 8 }}>
                    <div style={{ fontSize: 13, color: '#eab308', fontWeight: 700 }}>
                      {s.themed_name || '—'}
                      <span style={{ color: '#57534e', fontWeight: 400, fontSize: 11 }}> ← {s.original}</span>
                    </div>
                    {s.art_prompt && (
                      <div style={{ fontSize: 11, color: '#78716c', lineHeight: 1.4, marginTop: 3, fontStyle: 'italic' }}>
                        {s.art_prompt}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ fontSize: 10, color: '#44403c', marginTop: 12 }}>
            A quick approximation from a 3-card sample — the full build distributes these motifs across all 100 cards.
          </div>
        </div>
      )}
    </div>
  )
}
