// ── 3D Commander Generator ──────────────────────────────────────────────────
// Pure JSX for the "Generate 3D Model (STL)" block on the deck-result screen.
// State + the fetch/SSE handler live in the `useGenerate3D` hook (StepDeck.jsx);
// this component just renders whatever state it's handed. Extracted verbatim.
export default function ThreeDPrintPanel({ single, hasRender, state, msg, stlUrl, health, onGenerate, onReset }) {
  return (
    <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #292524' }}>
      <div style={{ fontSize: 10, color: '#57534e', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>3D Print</div>
      {single && !hasRender && (
        <div style={{ fontSize: 11.5, color: '#78716c', marginBottom: 8, lineHeight: 1.5 }}>
          Needs generated art — a 3D model is sculpted from the card's artwork.
        </div>
      )}

      {state === 'idle' || state === 'error' ? (
        <div>
          <button
            onClick={onGenerate}
            style={{
              fontSize: 13, padding: '8px 18px', borderRadius: 8, border: '1px solid #44403c',
              background: '#1c1917', color: '#d6d3d1', cursor: 'pointer', fontFamily: 'inherit',
              display: 'flex', alignItems: 'center', gap: 8,
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = '#292524'}
            onMouseLeave={e => e.currentTarget.style.background = '#1c1917'}
          >
            <span style={{ fontSize: 16 }}>🧊</span>
            Generate 3D Model (STL)
          </button>
          {state === 'error' && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, color: '#f87171', marginBottom: 4 }}>⚠ {msg}</div>
              {health?.hint && (
                <div style={{ fontSize: 11, color: '#57534e' }}>{health.hint}</div>
              )}
              {health?.missing?.length > 0 && (
                <div style={{ marginTop: 6, padding: '8px 10px', background: '#1c1917', borderRadius: 6, border: '1px solid #292524' }}>
                  <div style={{ fontSize: 11, color: '#78716c', marginBottom: 4 }}>Missing models:</div>
                  {health.missing.map(m => (
                    <div key={m} style={{ fontSize: 11, color: '#a8a29e', fontFamily: 'monospace' }}>• {m}</div>
                  ))}
                  <div style={{ fontSize: 11, color: '#57534e', marginTop: 4 }}>
                    Run: <code style={{ color: '#86efac' }}>python model3d.py --download-models</code>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ) : state === 'done' ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <a
            href={stlUrl}
            download
            style={{
              fontSize: 13, padding: '8px 18px', borderRadius: 8, border: '1px solid #166534',
              background: '#14532d', color: '#86efac', cursor: 'pointer', fontFamily: 'inherit',
              display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none',
            }}
          >
            <span style={{ fontSize: 16 }}>⬇</span>
            Download STL
          </a>
          <button
            onClick={onReset}
            style={{ fontSize: 12, padding: '6px 12px', borderRadius: 6, border: '1px solid #292524', background: '#1c1917', color: '#78716c', cursor: 'pointer', fontFamily: 'inherit' }}
            title="Generate again with a new random seed"
          >↺ Regenerate</button>
        </div>
      ) : (
        /* loading / rmbg / trellis / converting */
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{ fontSize: 18, animation: 'spin-slow 1.5s linear infinite' }}>⚙️</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 4 }}>
                {state === 'loading'    && '🔍 Checking system…'}
                {state === 'rmbg'       && '✂️ Removing background…'}
                {state === 'trellis'    && '🧊 Generating 3D mesh (Hunyuan3D v2)…'}
                {state === 'converting' && '🔧 Exporting STL…'}
              </div>
              {/* Progress steps */}
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                {[
                  { key: 'rmbg',       label: 'BG Removal',  icon: '✂️' },
                  { key: 'trellis',    label: '3D Mesh',     icon: '🧊' },
                  { key: 'converting', label: 'STL Export',  icon: '🔧' },
                ].map((step, i) => {
                  const stepOrder = { loading: -1, rmbg: 0, trellis: 1, converting: 2, done: 3 }
                  const current  = stepOrder[state] ?? 0
                  const mine     = i
                  const active   = current === mine
                  const done     = current > mine
                  return (
                    <div key={step.key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <div style={{
                        fontSize: 10, padding: '2px 8px', borderRadius: 10,
                        background: done ? '#14532d' : active ? '#422006' : '#0c0a09',
                        border: `1px solid ${done ? '#166534' : active ? '#ca8a04' : '#292524'}`,
                        color: done ? '#86efac' : active ? '#fde047' : '#57534e',
                      }}>
                        {done ? '✓ ' : active ? '⟳ ' : ''}{step.label}
                      </div>
                      {i < 2 && <div style={{ width: 16, height: 1, background: '#292524' }} />}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
          {msg && (
            <div style={{ fontSize: 11, color: '#57534e', fontFamily: 'monospace', marginTop: 4 }}>
              {msg}
            </div>
          )}
          <div style={{ fontSize: 11, color: '#57534e', marginTop: 4 }}>
            ⏱ 3D mesh generation takes 2–5 minutes on RTX 3090
          </div>
        </div>
      )}
    </div>
  )
}
