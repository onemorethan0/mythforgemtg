// Simulation-grounded strength panel (MythGauntlet, Myth Suite C3) — shared by
// the import preview (StepCommander) and the result screen's Measure panel
// (StepDeck), so the two surfaces can't drift. Pure presentation: pass the
// `simulation` object exactly as the API returns it
// ({engine_version, power_profile, unresolved}).
export default function SimStrengthPanel({ simulation }) {
  const pp = simulation?.power_profile
  const AC = '#38bdf8'
  // MythGauntlet is the ONLY bracket authority now. Forge used to ship its own heuristic
  // estimator (deck_analysis.py) as a fallback and render it above this panel — two bracket
  // opinions on one screen, and the copy drifted (it still applied tutor restrictions that
  // the October 2025 bracket update removed). The duplicate is gone, so when :8020 is down
  // we say so plainly instead of substituting a worse answer.
  if (!pp) {
    return (
      <div style={{ background: '#0c0a09', border: '1px solid #292524', borderLeft: '3px solid #57534e',
                    borderRadius: 10, padding: 14, marginTop: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#d6d3d1', marginBottom: 6 }}>
          Bracket &amp; strength unavailable
        </div>
        <div style={{ fontSize: 11.5, color: '#a8a29e', lineHeight: 1.55 }}>
          MythGauntlet measures this by simulating games; it isn’t reachable on <code>:8020</code>.
          Start Myth Forge via <b>manage.bat</b> (it launches MythGauntlet automatically), or run{' '}
          <code style={{ color: '#d6d3d1' }}>mythgauntlet serve</code> yourself, then re-preview.
        </div>
      </div>
    )
  }
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
      {Array.isArray(pp.bracket_reasons) && pp.bracket_reasons.length > 0 && (
        <details style={{ marginBottom: 10 }}>
          <summary style={{ fontSize: 11, color: '#78716c', cursor: 'pointer', userSelect: 'none' }}>
            Why this bracket?
          </summary>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {pp.bracket_reasons.map((r, i) => (
              <li key={i} style={{ fontSize: 11, color: '#a8a29e', lineHeight: 1.5 }}>{r}</li>
            ))}
          </ul>
        </details>
      )}
      {simulation.combos?.checked && simulation.combos.total > 0 && (() => {
        const cb = simulation.combos
        const relColor = { 'fast-win': '#ef4444', strong: '#f97316', slow: '#eab308' }
        const shown = cb.items.slice(0, 6)
        return (
          <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #44403c' }}>
            <div style={{ fontSize: 11.5, color: '#d6d3d1', fontWeight: 600, marginBottom: 6 }}>
              Combos: {cb.total} in deck
              <span style={{ color: '#78716c', fontWeight: 400 }}>
                {' '}({cb.terminal} terminal, {cb.advantage} need an outlet
                {cb.nondeterministic ? `, ${cb.nondeterministic} non-deterministic` : ''})
              </span>
            </div>
            {shown.map((it, i) => {
              const rc = relColor[it.reliability] || '#eab308'
              return (
                <div key={i} style={{ marginBottom: 6 }}>
                  <div style={{ fontSize: 11, color: '#e7e5e4', lineHeight: 1.4 }}>
                    <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 10, marginRight: 6, background: `${rc}22`, color: rc, border: `1px solid ${rc}` }}>
                      {it.reliability}
                    </span>
                    {it.cards.join(' + ')}
                  </div>
                  <div style={{ fontSize: 10, color: '#78716c', marginLeft: 2, marginTop: 1 }}>
                    {it.produces.join('; ')}
                  </div>
                  <div style={{ fontSize: 10, color: '#a8a29e', marginLeft: 2 }}>
                    {it.pieces} pieces · {it.mana_value} mana · {it.terminal ? 'terminal' : 'needs an outlet'}
                    {it.needs_commander ? ' · commander-dependent' : ''}
                    {it.deterministic === false ? ' · ⚠ non-deterministic' : ''}
                    {it.spellbook_tag ? ` · Spellbook ${it.spellbook_tag}` : ''}
                  </div>
                </div>
              )
            })}
            {cb.total > shown.length && (
              <div style={{ fontSize: 10, color: '#78716c' }}>… and {cb.total - shown.length} more</div>
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
        {pp.go_off && (
          <span title="A storm/spellslinger nut draw reaches lethal off the combat clock" style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#7c2d1222', border: '1px solid #f97316', color: '#fdba74' }}>
            Storm go-off{pp.go_off_turn ? <b style={{ color: '#fed7aa' }}> ~T{pp.go_off_turn}</b> : null}
          </span>
        )}
        {pp.overrun_alpha && (
          <span title="A wide board + one-shot team pump kills in one swing on the nut draw" style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#14532d22', border: '1px solid #4ade80', color: '#86efac' }}>
            Overrun alpha strike
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: '#a8a29e', lineHeight: 1.5 }}>{pp.bracket_hint}</div>
      {simulation.engine_version && (
        <div style={{ fontSize: 10, color: '#57534e', marginTop: 6 }}>engine v{simulation.engine_version}</div>
      )}
    </div>
  )
}
