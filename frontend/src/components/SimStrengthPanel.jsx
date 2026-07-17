// Simulation-grounded strength panel (MythGauntlet, Myth Suite C3) — shared by
// the import preview (StepCommander) and the result screen's Measure panel
// (StepDeck), so the two surfaces can't drift. Pure presentation: pass the
// `simulation` object exactly as the API returns it
// ({engine_version, power_profile, unresolved}).
export default function SimStrengthPanel({ simulation }) {
  const pp = simulation?.power_profile
  if (!pp) return null
  const AC = '#38bdf8'
  const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
  const bar = (label, val, suffix = '') => (
    <div style={{ marginBottom: 7 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: '#a8a29e', marginBottom: 2 }}>
        <span>{label}</span>
        <b style={{ color: '#e7e5e4' }}>{val == null ? '—' : `${Math.round(val)}${suffix}`}</b>
      </div>
      <div style={{ height: 5, borderRadius: 4, background: '#1c1917', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, val || 0))}%`, background: AC }} />
      </div>
    </div>
  )
  const speed = pp.speed_avg_kill_turn
    ? `turn ${pp.speed_avg_kill_turn.toFixed(1)} (${pct(pp.speed_kill_rate)})`
    : `no goldfish kill (${pct(pp.speed_kill_rate)})`
  return (
    <div style={{ background: '#0c0a09', border: `1px solid ${AC}44`, borderLeft: `3px solid ${AC}`, borderRadius: 10, padding: 14, marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#d6d3d1' }}>Simulation-grounded strength</span>
        <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 20, background: `${AC}22`, color: AC, border: `1px solid ${AC}` }}>MythGauntlet</span>
      </div>
      <div style={{ fontSize: 11, color: '#78716c', marginBottom: 10 }}>
        Measured by simulating games — not a static heuristic.
      </div>
      {pp.bracket_estimate && (() => {
        const BR = { 1: '#4ade80', 2: '#a3e635', 3: '#eab308', 4: '#f97316', 5: '#ef4444' }
        const bc = BR[pp.bracket_estimate] || '#eab308'
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: '#a8a29e' }}>Simulated bracket</span>
            <span style={{ fontSize: 13, fontWeight: 800, padding: '2px 12px', borderRadius: 20, background: `${bc}22`, color: bc, border: `1px solid ${bc}` }}>
              {pp.bracket_estimate}. {pp.bracket_label}
            </span>
            {pp.bracket_confidence != null && (
              <span style={{ fontSize: 10.5, color: '#78716c' }}>{Math.round(pp.bracket_confidence * 100)}% conf.</span>
            )}
          </div>
        )
      })()}
      {bar('Consistency', pp.consistency, '/100')}
      {bar('Resilience vs a board wipe', pp.resilience, '/100')}
      {pp.interaction != null && bar('Interaction', pp.interaction, '/100')}
      {pp.ceiling != null && bar('Ceiling (nut draw)', pp.ceiling, '/100')}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '4px 0 8px' }}>
        <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e' }}>
          Speed: <b style={{ color: '#e7e5e4' }}>{speed}</b>
        </span>
        <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e' }}>
          Cards simulated at high fidelity: <b style={{ color: '#e7e5e4' }}>{pct(pp.semantics_coverage)}</b>
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#a8a29e', lineHeight: 1.5 }}>{pp.bracket_hint}</div>
      {simulation.engine_version && (
        <div style={{ fontSize: 10, color: '#57534e', marginTop: 6 }}>engine v{simulation.engine_version}</div>
      )}
    </div>
  )
}
