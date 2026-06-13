import { useEffect, useState } from 'react'

// WUBRG chip styling for the colour-faction display.
const COLOR_META = {
  W: { name: 'White', glyph: 'W', bg: '#f8f4e6', fg: '#3a3320' },
  U: { name: 'Blue',  glyph: 'U', bg: '#3b82f6', fg: '#0b1f3a' },
  B: { name: 'Black', glyph: 'B', bg: '#3f3f46', fg: '#e4e4e7' },
  R: { name: 'Red',   glyph: 'R', bg: '#ef4444', fg: '#3a0b0b' },
  G: { name: 'Green', glyph: 'G', bg: '#22c55e', fg: '#0b2a16' },
}

// "Preview the creative direction" — a cheap, pre-build look at how the app will
// interpret the user's deck idea. Calls POST /api/deck/theme-preview, which builds
// the world bible (must-include motifs + invented signature details + palette) and
// themes a 3-card sample, so the user can iterate on their inputs before committing
// to a full ~30-minute build. The must-include chips double as the faithfulness
// contract: ✓ = the motif shows up in the sample art, ⚠ = not yet (try rephrasing).
export default function ThemePreview({ commanderName, themeSpec, artStyle, creativity, commanderPrompt, llmModel,
                                        canRenderArt = false, modelSpeed = 'quality', checkpoint = '', genSettings = null }) {
  const [loading, setLoading] = useState(false)
  const [data, setData]       = useState(null)
  const [error, setError]     = useState('')
  // Visual taste test: render the previewed prompts as real art (~30s each)
  const [artJob, setArtJob]     = useState(null)   // job_id while rendering
  const [artState, setArtState] = useState(null)   // last polled status payload
  const [artError, setArtError] = useState('')

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

  // Kick off a visual taste test: render the previewed prompts as real art.
  async function renderSamples() {
    if (!data?.samples?.length) return
    setArtError(''); setArtState(null)
    try {
      const res = await fetch('/api/deck/style-sample', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          samples: data.samples.map(s => ({
            themed_name: s.themed_name, art_prompt: s.art_prompt, type_line: s.type_line,
          })),
          art_style:    artStyle || 'mtg_fantasy',
          model_speed:  modelSpeed || 'quality',
          checkpoint:   checkpoint || null,
          llm_model:    llmModel || null,
          gen_settings: genSettings || null,
        }),
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.detail || `Sample render failed (${res.status})`)
      setArtJob(body.job_id)
    } catch (e) {
      setArtError(String(e.message || e))
    }
  }

  // Poll the sample job every 3s until done/error.
  useEffect(() => {
    if (!artJob) return
    let stop = false
    const tick = async () => {
      try {
        const res = await fetch(`/api/deck/style-sample/${artJob}`)
        const body = await res.json()
        if (stop) return
        setArtState(body)
        if (body.status === 'building') setTimeout(tick, 3000)
        else if (body.status === 'error') { setArtError(body.error || 'Sample render failed'); setArtJob(null) }
        else setArtJob(null)   // done
      } catch {
        if (!stop) setTimeout(tick, 4000)
      }
    }
    tick()
    return () => { stop = true }
  }, [artJob])

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

          {/* Colour factions — the set-cohesion layer (each colour is a faction) */}
          {wb.color_factions && Object.keys(wb.color_factions).length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#a8a29e', marginBottom: 6 }}>
                Colour factions <span style={{ color: '#57534e', fontWeight: 400 }}>— every card of a colour belongs to its faction, so the deck reads as one set</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {['W', 'U', 'B', 'R', 'G'].filter(c => wb.color_factions[c]).map(c => {
                  const f = wb.color_factions[c]
                  const meta = COLOR_META[c]
                  return (
                    <div key={c} style={{ padding: '8px 12px', background: '#1c1917', border: '1px solid #292524', borderRadius: 8, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                      <span title={meta.name} style={{ flexShrink: 0, width: 20, height: 20, borderRadius: '50%', background: meta.bg, color: meta.fg, fontSize: 12, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #00000044' }}>{meta.glyph}</span>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: '#f5f5f4' }}>{f.name}</div>
                        {f.people && <div style={{ fontSize: 11, color: '#a8a29e', marginTop: 1 }}>{f.people}</div>}
                        {f.aesthetic && <div style={{ fontSize: 11, color: '#78716c', marginTop: 2 }}>{f.aesthetic}</div>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Lore — the connective tissue between factions */}
          {wb.lore && (
            <div style={{ marginBottom: 14, padding: '10px 14px', background: '#150f24', border: '1px solid #4c1d9555', borderRadius: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#a78bfa', marginBottom: 4 }}>Lore</div>
              <div style={{ fontSize: 12, color: '#d6d3d1', lineHeight: 1.5, fontStyle: 'italic' }}>{wb.lore}</div>
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

          {/* Visual taste test — render the previewed prompts as real art */}
          {canRenderArt && data?.samples?.length > 0 && (
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #292524' }}>
              {!artJob && !artState?.images?.length && (
                <button
                  onClick={renderSamples}
                  style={{
                    fontSize: 13, padding: '9px 16px', borderRadius: 10, cursor: 'pointer',
                    background: 'linear-gradient(180deg,#ca8a04,#854d0e)', border: '1px solid #eab308',
                    color: '#0c0a09', fontFamily: 'inherit', fontWeight: 700,
                    display: 'flex', alignItems: 'center', gap: 8,
                  }}
                >
                  <span>🎨</span> Render these as real art (~2 min)
                </button>
              )}
              {artJob && (
                <div style={{ fontSize: 12, color: '#a8a29e' }}>
                  ⏳ Painting{artState?.current ? <> — <em style={{ color: '#eab308' }}>{artState.current}</em></> : '…'}
                  <span style={{ color: '#57534e' }}> ({(artState?.images?.length || 0)}/{artState?.total || data.samples.length} done — first image loads the model, ~60s)</span>
                </div>
              )}
              {artError && (
                <div style={{ marginTop: 8, padding: '8px 12px', background: '#1f0a0a', border: '1px solid #7f1d1d', borderRadius: 8, fontSize: 12, color: '#fca5a5' }}>
                  {artError}
                </div>
              )}
              {artState?.images?.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 10, marginTop: 10 }}>
                  {artState.images.filter(im => im.ok && im.url).map(im => (
                    <figure key={im.idx} style={{ margin: 0 }}>
                      <img src={im.url} alt={im.themed_name}
                           style={{ width: '100%', borderRadius: 8, border: '1px solid #44403c', display: 'block' }} />
                      <figcaption style={{ fontSize: 11, color: '#eab308', marginTop: 4, fontWeight: 700 }}>
                        {im.themed_name}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              )}
              {!artJob && artState?.images?.length > 0 && (
                <button
                  onClick={renderSamples}
                  style={{ marginTop: 10, fontSize: 11, color: '#78716c', background: 'none', border: '1px solid #292524', borderRadius: 8, padding: '5px 12px', cursor: 'pointer', fontFamily: 'inherit' }}
                >
                  🎲 Re-roll samples
                </button>
              )}
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
