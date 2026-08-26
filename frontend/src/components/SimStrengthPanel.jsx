import { TERMS, WINCON_ROLE_TERMS, BRACKET_TERMS } from '../glossary'
import PowerRadar from './PowerRadar'

// A label with a native-tooltip glossary definition attached. Plain `title=` (no custom
// floating panel) — one sentence doesn't need CardHover-style machinery, and `title` is
// already this file's convention (the plays-up banner below, the Speed chip). The small
// "ⓘ" is the only addition: a bare `title` on a label gives no visual hint it's hoverable.
// NOTE: a Python test locates the plays-up banner below by the first occurrence of its
// prop name in this file's source text (grep the engine tests before quoting it up here).
function Term({ children, def }) {
  return (
    <span title={def} style={{ cursor: 'help', borderBottom: '1px dotted #57534e' }}>
      {children}<span style={{ color: '#57534e', fontSize: '0.85em', marginLeft: 2 }}>ⓘ</span>
    </span>
  )
}

// Simulation-grounded strength panel (MythGauntlet, Myth Suite C3) — shared by
// the import preview (StepCommander) and the result screen's Measure panel
// (StepDeck), so the two surfaces can't drift. Pure presentation: pass the
// `simulation` object exactly as the API returns it
// ({engine_version, power_profile, unresolved}).
export default function SimStrengthPanel({ simulation }) {
  const pp = simulation?.power_profile
  // Deck-specific narrative (archetype/gameplan/pod placement/key cards/strengths &
  // weaknesses) — deterministic, computed for free alongside power_profile by the same
  // analyze_deck call (mythgauntlet.ratings.insight), but historically dropped at the
  // Forge/engine boundary (_gauntlet_analyze only ever forwarded power_profile+combos).
  const insight = simulation?.insight
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
  const bar = (label, val, suffix = '', detail = null, term = null) => (
    <div style={{ marginBottom: 7 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: '#a8a29e', marginBottom: 2 }}>
        <span>{term ? <Term def={term}>{label}</Term> : label}</span>
        <b style={{ color: '#e7e5e4' }}>{val == null ? '—' : `${Math.round(val)}${suffix}`}</b>
      </div>
      <div style={{ height: 5, borderRadius: 4, background: '#1c1917', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, val || 0))}%`, background: AC }} />
      </div>
      {detail && (
        <div style={{ fontSize: 10, color: '#78716c', marginTop: 2, lineHeight: 1.4 }}>{detail}</div>
      )}
    </div>
  )
  // Prefer the engine's own authored prose (insight.axis_why — the SAME numbers, written by
  // the same code that builds the CLI report) when it's present; the hand-rolled versions
  // below are the fallback for a caller that only has power_profile (e.g. a cached response
  // from before `insight` was wired through the Forge/engine boundary).
  const why = insight?.axis_why || {}
  // "2 removal, 6 counters, 0 wipes; breadth 2/3" -- the same breakdown the CLI has always
  // shown, now reaching the panel instead of just a bare 0-100 score.
  const interactionDetail = why.Interaction || (pp.interaction_answers != null && (
    <>
      {pp.interaction_answers} answer{pp.interaction_answers === 1 ? '' : 's'}
      {pp.interaction_effective_answers != null
        ? ` (${pp.interaction_effective_answers.toFixed(1)} castable-weighted)` : ''}
      {pp.interaction_spot_removal != null && (
        <> — {pp.interaction_spot_removal} removal, {pp.interaction_counterspells} counters,{' '}
          {pp.interaction_board_wipes} wipes; breadth {pp.interaction_breadth}/3</>
      )}
    </>
  ))
  // "vs a turn-5 board wipe (100% -> 100% kill rate, +0.0 turns to kill)" -- what the
  // resilience score actually simulated, not just the composite number.
  const resilienceDetail = why.Resilience || (pp.resilience_wipe_turn != null && (
    <>
      vs a turn-{pp.resilience_wipe_turn} board wipe ({pct(pp.resilience_clean_kill_rate)} → {' '}
      {pct(pp.resilience_wiped_kill_rate)} kill rate
      {pp.resilience_kill_delay_turns != null
        ? `, +${pp.resilience_kill_delay_turns.toFixed(1)} turns to kill` : ''})
    </>
  ))
  // The Pod axis answers a DIFFERENT question than the goldfish speed/ceiling numbers above:
  // can this deck actually close a real ~4-player game, or only a 1v1 duel? A deck can read
  // fast and consistent in every other row and still barely dent a pod (Prismari-class storm
  // decks: 100% duel-close, single-digit pod-close) -- exactly the duel-vs-pod gap this axis
  // exists to surface, and it was computed all along but never rendered until now.
  const podDetail = why['Pod (multiplayer)'] || (pp.pod != null && (
    pp.pod_close_turn != null ? (
      <>
        closes a {(pp.pod_opponents ?? 3) + 1}-player pod ~turn {Math.round(pp.pod_close_turn)}{' '}
        ({pct(pp.pod_close_rate)} of games) — duel-close {pct(pp.pod_duel_close_rate)}
        {pp.pod_via_finisher ? ' · via a game-ending finisher' : ''}
      </>
    ) : (
      <>
        doesn&rsquo;t reliably close a full {(pp.pod_opponents ?? 3) + 1}-player pod within the
        horizon (duel-close {pct(pp.pod_duel_close_rate)}) — reads faster 1-on-1 than at a
        real table
      </>
    )
  ))
  // Consistency and Ceiling had NO detail line before insight.axis_why existed to supply
  // one — there was no raw field on power_profile to hand-roll a fallback from.
  const consistencyDetail = why.Consistency || null
  const ceilingDetail = why.Ceiling || null
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
      {insight?.archetype && (
        <div style={{ marginBottom: 10 }}>
          <span style={{
            fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 12,
            background: '#1c1917', border: '1px solid #57534e', color: '#d6d3d1', marginRight: 6,
          }}>
            {insight.archetype}
          </span>
          {insight.gameplan && (
            <span style={{ fontSize: 11.5, color: '#a8a29e', lineHeight: 1.5 }}>{insight.gameplan}</span>
          )}
        </div>
      )}
      {pp.bracket_estimate && (() => {
        const BR = { 1: '#4ade80', 2: '#a3e635', 3: '#eab308', 4: '#f97316', 5: '#ef4444' }
        const bc = BR[pp.bracket_estimate] || '#eab308'
        const bt = BRACKET_TERMS[pp.bracket_estimate]
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: '#a8a29e' }}>
              <Term def="WotC's official 1-5 power-level system for Commander matchmaking. Estimated here from what the deck actually holds (Game Changers, combos, mass land denial, extra turns) and how it simulates, not from a target you picked.">Simulated bracket</Term>
            </span>
            <span
              title={bt ? `${bt.label}: ${bt.desc}` : undefined}
              style={{ fontSize: 13, fontWeight: 800, padding: '2px 12px', borderRadius: 20, background: `${bc}22`, color: bc, border: `1px solid ${bc}`, cursor: bt ? 'help' : 'default' }}
            >
              {pp.bracket_estimate}. {pp.bracket_label}
            </span>
            {pp.bracket_confidence != null && (
              <span
                title="How much evidence backs this estimate — more Game Changers/combos/gates firing decisively raises confidence; a borderline read lowers it."
                style={{ fontSize: 10.5, color: '#78716c', cursor: 'help', borderBottom: '1px dotted #57534e' }}
              >
                {Math.round(pp.bracket_confidence * 100)}% conf.
              </span>
            )}
          </div>
        )
      })()}
      {/* The casual headline takeaway: which pod does this belong in, in plain English —
          not just the bracket number, but what it MEANS to bring this to a table (e.g.
          "will overwhelm casual tables" / "a fair fit for a casual Bracket 2 pod"). Reads
          the same bracket+plays_up state as the badge above, so the two never disagree. */}
      {insight?.pod_read && (
        <div style={{
          fontSize: 11.5, color: '#d6d3d1', lineHeight: 1.5, marginBottom: 10,
          padding: '6px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #292524',
        }}>
          {insight.pod_read}
        </div>
      )}
      {/* The B2/B3 boundary is NOT resolvable from card gates, and the engine says so.
          `plays_up` marks a deck the Game Changer gate caps at Core OR Exhibition while it
          sits on the Core/Upgraded edge — measured, 40% of decks their own authors call
          Upgraded also run zero Game Changers on the Core side of this gate, 14% on the
          Exhibition side (scripts/bracket_accuracy.py --json, full 297-deck corpus,
          2026-08-24; the Exhibition side used to carry no flag at all, on the never-measured
          assumption that a thin manabase also meant low power — checking it found otherwise).
          Amber, not red: this describes uncertainty, not a defect — same convention as the
          manabase panel's `ramp-dependent`. */}
      {pp.bracket_plays_up && (
        <div
          title={pp.bracket_estimate === 1
            ? '0 Game Changers and a thin manabase cap this at Exhibition. The Game Changer '
              + 'gate is nearly silent on power once it reads zero, so 14% of decks placed '
              + 'here are called Upgraded by their own builders too — read the axes below.'
            : '0 Game Changers caps this at Core. Measured over the corpus, 40% of decks '
              + 'their authors call Upgraded also run none, so a zero-Game-Changer Core '
              + 'verdict cannot rule Upgraded out. Read the axes below, and tell your pod '
              + 'it sits on the line.'}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10,
            padding: '6px 10px', borderRadius: 8,
            background: '#1c1408', border: '1px solid #a16207', cursor: 'help',
          }}
        >
          <span style={{ fontSize: 13, color: '#fde047' }}>↗</span>
          <span style={{ fontSize: 11.5, color: '#fde047', lineHeight: 1.45 }}>
            {pp.bracket_estimate === 1 ? (
              <>
                <strong>A thin manabase, not necessarily a weak deck.</strong> No Game
                Changers and inconsistent colours cap this at Bracket 1, but 14% of decks
                placed here are called Bracket 3 by their own builders too — this can&rsquo;t
                be settled from the card list alone.
              </>
            ) : (
              <>
                <strong>Sits on the Core / Upgraded line.</strong> No Game Changers caps this
                at Bracket 2, but 40% of decks their own builders call Bracket 3 run none
                either — this boundary can&rsquo;t be settled from the card list alone.
              </>
            )}
          </span>
        </div>
      )}
      {Array.isArray(pp.game_changer_names) && pp.game_changer_names.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11, color: '#78716c', marginBottom: 4 }}>
            <Term def={TERMS.game_changers}>Game Changers</Term> ({pp.game_changer_names.length}):
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {pp.game_changer_names.map((name) => (
              <span
                key={name}
                style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#78350f22', border: '1px solid #d97706', color: '#fbbf24' }}
              >
                {name}
              </span>
            ))}
          </div>
        </div>
      )}
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
                {' '}(<span title="Wins the game outright once every piece is assembled — no extra step needed." style={{ cursor: 'help', borderBottom: '1px dotted #57534e' }}>{cb.terminal} terminal</span>, <span title="Generates a resource loop (extra mana, tokens, etc.) but still needs something else on the board to actually close the game." style={{ cursor: 'help', borderBottom: '1px dotted #57534e' }}>{cb.advantage} need an outlet</span>
                {cb.nondeterministic ? <>, <span title="The loop's result depends on a coin flip, dice roll, or an opponent's choice (CR 720) — it can't be forced to a win the way a deterministic combo can." style={{ cursor: 'help', borderBottom: '1px dotted #57534e' }}>{cb.nondeterministic} non-deterministic</span></> : ''})
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
      <PowerRadar axes={[
        { key: 'consistency', label: 'Consistency', value: pp.consistency, term: TERMS.consistency },
        { key: 'resilience', label: 'Resilience', value: pp.resilience, term: TERMS.resilience },
        { key: 'interaction', label: 'Interaction', value: pp.interaction, term: TERMS.interaction },
        { key: 'ceiling', label: 'Ceiling', value: pp.ceiling, term: TERMS.ceiling },
        { key: 'pod', label: 'Pod', value: pp.pod, term: TERMS.pod },
      ]} />
      {bar('Consistency', pp.consistency, '/100', consistencyDetail, TERMS.consistency)}
      {bar('Resilience vs a board wipe', pp.resilience, '/100', resilienceDetail, TERMS.resilience)}
      {pp.interaction != null && bar('Interaction', pp.interaction, '/100', interactionDetail, TERMS.interaction)}
      {pp.ceiling != null && bar('Ceiling (nut draw)', pp.ceiling, '/100', ceilingDetail, TERMS.ceiling)}
      {pp.pod != null && bar('Pod (4-player game)', pp.pod, '/100', podDetail, TERMS.pod)}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '4px 0 8px' }}>
        <span title={why.Speed ? `${why.Speed}\n\n${TERMS.speed}` : TERMS.speed} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e', cursor: 'help' }}>
          Speed: <b style={{ color: '#e7e5e4' }}>{speed}</b>
        </span>
        <span title={TERMS.semantics_coverage} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e', cursor: 'help' }}>
          Cards simulated at high fidelity: <b style={{ color: '#e7e5e4' }}>{pct(pp.semantics_coverage)}</b>
        </span>
        {pp.go_off && (
          <span title={TERMS.storm_go_off} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#7c2d1222', border: '1px solid #f97316', color: '#fdba74', cursor: 'help' }}>
            Storm go-off{pp.go_off_turn ? <b style={{ color: '#fed7aa' }}> ~T{pp.go_off_turn}</b> : null}
          </span>
        )}
        {pp.overrun_alpha && (
          <span title={TERMS.overrun_alpha} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#14532d22', border: '1px solid #4ade80', color: '#86efac', cursor: 'help' }}>
            Overrun alpha strike
          </span>
        )}
        {pp.wincon_redundancy?.applicable && pp.wincon_redundancy.roles.map((r) => (
          <span
            key={r.role}
            title={
              (WINCON_ROLE_TERMS[r.role] ? `${WINCON_ROLE_TERMS[r.role]}\n\n` : '') +
              (r.pieces_to_disable == null
                ? `Removing every ${r.role.replace(/_/g, ' ')} card alone doesn't stop this kill -- another wincon is independently sufficient`
                : `${r.pieces_to_disable} of ${r.contributing_cards.length} ${r.role.replace(/_/g, ' ')} card(s) must be answered to fully disable this kill${r.involves_commander ? ' (includes a commander -- recastable, not truly gone)' : ''}`)
            }
            style={{ fontSize: 11, padding: '2px 8px', borderRadius: 12, background: '#1e1b4b22', border: '1px solid #818cf8', color: '#c7d2fe', cursor: 'help' }}
          >
            {r.role.replace(/_/g, ' ')}: {r.pieces_to_disable == null ? '?' : r.pieces_to_disable} to stop
          </span>
        ))}
      </div>
      {((insight?.strengths?.length || 0) > 0 || (insight?.weaknesses?.length || 0) > 0) && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 10,
          padding: '8px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #292524',
        }}>
          {insight.strengths?.length > 0 && (
            <div style={{ flex: '1 1 160px' }}>
              <div style={{ fontSize: 10.5, color: '#78716c', marginBottom: 4 }}>Strengths</div>
              {insight.strengths.map((s, i) => (
                <div key={i} style={{ fontSize: 11, color: '#86efac', lineHeight: 1.5, display: 'flex', gap: 5 }}>
                  <span>✓</span><span>{s}</span>
                </div>
              ))}
            </div>
          )}
          {insight.weaknesses?.length > 0 && (
            <div style={{ flex: '1 1 160px' }}>
              <div style={{ fontSize: 10.5, color: '#78716c', marginBottom: 4 }}>Weaknesses</div>
              {insight.weaknesses.map((w, i) => (
                <div key={i} style={{ fontSize: 11, color: '#fca5a5', lineHeight: 1.5, display: 'flex', gap: 5 }}>
                  <span>⚠</span><span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {insight?.key_cards?.length > 0 && (
        <details style={{ marginBottom: 10 }}>
          <summary style={{ fontSize: 11, color: '#78716c', cursor: 'pointer', userSelect: 'none' }}>
            Key cards — what drives each role
          </summary>
          <div style={{ marginTop: 6 }}>
            {insight.key_cards.map((kc) => (
              <div key={kc.role} style={{ fontSize: 11, marginBottom: 4, lineHeight: 1.5 }}>
                <span style={{ color: '#78716c' }}>{kc.role}: </span>
                <span style={{ color: '#d6d3d1' }}>{kc.names.join(', ')}</span>
                {kc.more > 0 && <span style={{ color: '#78716c' }}> (+{kc.more} more)</span>}
              </div>
            ))}
          </div>
        </details>
      )}
      <div style={{ fontSize: 12, color: '#a8a29e', lineHeight: 1.5 }}>{pp.bracket_hint}</div>
      {simulation.engine_version && (
        <div style={{ fontSize: 10, color: '#57534e', marginTop: 6 }}>engine v{simulation.engine_version}</div>
      )}
    </div>
  )
}
