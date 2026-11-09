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

// Table feel — EDHREC community salt, a casual-pod lens that is deliberately NOT part of the
// power radar above: a deck can be weak and salty, or strong and friendly. The score is a
// percentile among real decks, so the band words are relative ("saltier than most"), never
// a verdict on the pilot. Unmeasured (no salt store) says so instead of reading as friendly.
const SALT_BANDS = {
  friendly: { color: '#4ade80', label: 'Friendly', blurb: 'less salt than most decks' },
  spicy: { color: '#eab308', label: 'Spicy', blurb: 'a few cards a table may groan at' },
  salty: { color: '#ef4444', label: 'Salty', blurb: 'saltier than four in five decks' },
}

function TableFeel({ pp, detail }) {
  const band = SALT_BANDS[pp.table_feel_band]
  if (!band || pp.table_feel == null) {
    if (pp.table_feel_band !== 'unavailable') return null
    return (
      <div style={{ fontSize: 10.5, color: '#78716c', margin: '2px 0 8px' }}>
        <Term def={TERMS.table_feel}>Table feel</Term>: not measured
        {pp.table_feel_reason ? ` (${pp.table_feel_reason})` : ''}
      </div>
    )
  }
  const cards = pp.table_feel_salty_cards || []
  return (
    <div style={{ margin: '6px 0 10px', padding: '8px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #292524' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 11.5, color: '#a8a29e' }}>
          <Term def={TERMS.table_feel}>Table feel (community salt)</Term>
        </span>
        <span style={{ fontSize: 11, fontWeight: 700, padding: '1px 8px', borderRadius: 12, background: `${band.color}22`, color: band.color, border: `1px solid ${band.color}` }}>
          {band.label} · {Math.round(pp.table_feel)}
        </span>
      </div>
      <div style={{ height: 5, borderRadius: 4, background: '#0c0a09', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, pp.table_feel))}%`, background: band.color }} />
      </div>
      <div style={{ fontSize: 10, color: '#78716c', marginTop: 3, lineHeight: 1.4 }}>
        {detail || `saltier than ${Math.round(pp.table_feel)}% of decks — ${band.blurb}`}
      </div>
      {cards.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 6 }}>
          {cards.map((c) => (
            <span key={c.name} title={`EDHREC community salt ${c.salt.toFixed(2)} / 4`}
              style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 10, background: '#7f1d1d22', border: '1px solid #7f1d1d', color: '#fca5a5', cursor: 'help' }}>
              {c.name} <b style={{ color: '#fecaca' }}>{c.salt.toFixed(1)}</b>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// Table-contract dials (D3): Denial, Pace, Inevitability, each with the reasons the engine
// gave. They sit under the bracket badge so the line a pod hears reads "Bracket 2 · Denial
// High · Pace Long" -- what to say before shuffling up. They never change the bracket.
const DIAL_COLORS = {
  Low: '#4ade80', Medium: '#eab308', High: '#ef4444',
  Fast: '#ef4444', Typical: '#a8a29e', Long: '#38bdf8',
}
const DIAL_TERMS = {
  denial: 'How much it stops other players from playing: lock pieces and land denial count most, then counterspells, theft and extra turns. High at Bracket 1-2 means the pod should know before the game.',
  pace: "When it kills one opponent who never interacts (with combos when one comes first). Fast is turn 6 or earlier, inside the six turns Bracket 3 promises; Long is turn 11 or later, or rarely.",
  inevitability: 'How predictably it wins the same way: a reliable game-ending combo, and tutors that can find its pieces. High means games look alike; Low means they play out differently.',
}

function Dials({ dials }) {
  if (!dials) return null
  const rows = [['denial', 'Denial'], ['pace', 'Pace'], ['inevitability', 'Inevitability']]
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '-4px 0 10px' }}>
      {rows.map(([key, label]) => {
        const d = dials[key]
        if (!d) return null
        const c = DIAL_COLORS[d.band] || '#a8a29e'
        return (
          <span key={key} title={`${DIAL_TERMS[key]}\n\n${(d.reasons || []).join('\n')}`}
            style={{ fontSize: 11, padding: '2px 9px', borderRadius: 12, cursor: 'help', background: `${c}1a`, border: `1px solid ${c}`, color: '#d6d3d1' }}>
            {label} <b style={{ color: c }}>{d.band}</b>
          </span>
        )
      })}
    </div>
  )
}

// Denial (D2): what the deck does to OTHER players' turns. Lock pieces by name (a continuous
// effect that stops opponents untapping, casting, drawing, attacking or winning, with no way to
// pay around it), plus counterspells, lasting theft, extra turns and mass land denial. Like
// Table feel it sits beside power, not in it: the engine never moves the bracket on it.
const LOCK_KIND = {
  untap: 'keeps permanents tapped', spell_limit: 'limits spells', draw_limit: 'limits draws',
  attack: 'stops attacks', cant_lose: "can't be killed by damage", ability: 'shuts off abilities',
}

function Denial({ denial }) {
  if (!denial) return null
  const { locks = [], counterspells = 0, theft = 0, extra_turn_cards: extra = 0,
    mass_land_denial: mld = [] } = denial
  if (!locks.length && !counterspells && !theft && !extra && !mld.length) return null
  const parts = [
    counterspells ? `${counterspells} counterspell${counterspells > 1 ? 's' : ''}` : null,
    theft ? `${theft} theft card${theft > 1 ? 's' : ''}` : null,
    extra ? `${extra} extra-turn card${extra > 1 ? 's' : ''}` : null,
  ].filter(Boolean)
  return (
    <div style={{ margin: '6px 0 10px', padding: '8px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #292524' }}>
      <div style={{ fontSize: 11.5, color: '#a8a29e', marginBottom: 4 }}>
        <Term def="Cards that stop other players from playing: lock pieces (a lasting effect that keeps permanents tapped, limits spells or draws, stops attacks, makes a player unkillable by damage, or shuts off abilities, with no way to pay around it), counterspells, lasting theft, extra turns and mass land denial. Shown so the pod knows before the game; it does not change the bracket.">What it denies other players</Term>
      </div>
      {(locks.length > 0 || mld.length > 0) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: parts.length ? 5 : 0 }}>
          {locks.map((lk) => (
            <span key={lk.name} title={`Lock piece: ${LOCK_KIND[lk.kind] || lk.kind} -- "${lk.reason}"`}
              style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 10, background: '#4c1d9522', border: '1px solid #7c3aed', color: '#c4b5fd', cursor: 'help' }}>
              {lk.name} <span style={{ color: '#a78bfa' }}>· {LOCK_KIND[lk.kind] || lk.kind}</span>
            </span>
          ))}
          {mld.map((n) => (
            <span key={`mld-${n}`} title="Mass land denial: not allowed in Brackets 1-3"
              style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 10, background: '#7f1d1d22', border: '1px solid #b91c1c', color: '#fca5a5', cursor: 'help' }}>
              {n} <span style={{ color: '#f87171' }}>· land denial</span>
            </span>
          ))}
        </div>
      )}
      {parts.length > 0 && (
        <div style={{ fontSize: 10.5, color: '#a8a29e' }}>{parts.join(' · ')}</div>
      )}
    </div>
  )
}

// Weak against (B36): what a common answer punishes in this deck -- each row only past its
// corpus threshold, so an empty list means nothing stands out, not "no weaknesses".
const EXPOSURE_ICON = {
  graveyard: '🪦', commander: '👑', wipes: '🌊', artifacts: '⚙️', enchantments: '✨',
  flyers: '🪽', single_combo: '🔗', mana_base: '🌋', speed: '⏱',
}

function WeakAgainst({ exposure }) {
  if (!exposure?.length) return null
  return (
    <div style={{ margin: '6px 0 10px', padding: '8px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #292524' }}>
      <div style={{ fontSize: 11.5, color: '#a8a29e', marginBottom: 4 }}>
        <Term def="What common answers punish in this deck. Each line appears only when the deck leans on something more than about four in five Commander decks do (or, for wipes and speed, sits in the bottom quarter of its bracket), so a short list is a good sign.">Weak against</Term>
      </div>
      {exposure.map((e) => (
        <div key={e.key} title={(e.evidence || []).join(', ')}
          style={{ fontSize: 11, color: '#fdba74', lineHeight: 1.5, display: 'flex', gap: 6, cursor: e.evidence?.length ? 'help' : 'default' }}>
          <span>{EXPOSURE_ICON[e.key] || '•'}</span><span>{e.text}</span>
        </div>
      ))}
    </div>
  )
}

// Kill clock (B32) and combo clock (B33): when the deck kills an opponent who never interacts,
// as a range rather than one average, and how often each combo is assembled by each turn.
// `by_turn` keys arrive as strings (JSON object keys). Every number shown is the engine's;
// the component only lays them out, and hides itself when neither block is present (an older
// cached measurement).
const DAMAGE_COLOR = '#38bdf8'
const COMBO_COLOR = '#f97316'
const CLOCK_TURNS = [6, 8, 10]
const SPARK_TURNS = [3, 4, 5, 6, 7, 8, 9, 10]

const share = (byTurn, t) => (byTurn ? byTurn[String(t)] ?? byTurn[t] ?? null : null)

function ClockRow({ turn, damage, combined }) {
  const w = (v) => `${Math.max(0, Math.min(100, (v || 0) * 100))}%`
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '34px 1fr 74px', alignItems: 'center', gap: 6, marginBottom: 4 }}>
      <span style={{ fontSize: 10.5, color: '#a8a29e' }}>by T{turn}</span>
      <div style={{ position: 'relative', height: 7, borderRadius: 4, background: '#0c0a09', overflow: 'hidden' }}>
        {combined != null && (
          <div style={{ position: 'absolute', inset: 0, width: w(combined), background: COMBO_COLOR, opacity: 0.55 }} />
        )}
        <div style={{ position: 'absolute', inset: 0, width: w(damage), background: DAMAGE_COLOR }} />
      </div>
      <span style={{ fontSize: 10.5, color: '#e7e5e4', textAlign: 'right', whiteSpace: 'nowrap' }}>
        {damage == null ? '—' : `${Math.round(damage * 100)}%`}
        {combined != null && combined > (damage || 0) + 0.005 && (
          <span style={{ color: '#fdba74' }}> / {Math.round(combined * 100)}%</span>
        )}
      </span>
    </div>
  )
}

function ComboSpark({ byTurn }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 1, height: 14 }}
      title={SPARK_TURNS.map((t) => `T${t}: ${Math.round((share(byTurn, t) || 0) * 100)}%`).join('  ')}>
      {SPARK_TURNS.map((t) => (
        <span key={t} style={{ width: 4, height: `${Math.max(1, (share(byTurn, t) || 0) * 14)}px`, background: COMBO_COLOR, borderRadius: 1, opacity: 0.85 }} />
      ))}
    </span>
  )
}

const COMBO_KIND = {
  kill: 'kills the turn it assembles',
  kill_next_turn: 'kills the turn after (tokens without haste)',
  advantage: 'needs another card to win',
}

function KillClock({ killSpeed, comboClock }) {
  if (!killSpeed && !comboClock) return null
  const combos = comboClock?.combos || []
  const timed = combos.filter((c) => c.timed)
    .sort((a, b) => (a.turn_50 ?? 99) - (b.turn_50 ?? 99) || (a.turn_25 ?? 99) - (b.turn_25 ?? 99))
  const untimed = combos.filter((c) => !c.timed)
  const showCombined = comboClock && comboClock.combo_first_games > 0
  return (
    <div style={{ margin: '6px 0 10px', padding: '8px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #292524' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 11.5, color: '#a8a29e' }}>
          <Term def={TERMS.kill_clock}>How fast it kills (unopposed)</Term>
        </span>
        <span style={{ fontSize: 10, color: '#78716c', display: 'flex', gap: 8 }}>
          <span><span style={{ color: DAMAGE_COLOR }}>■</span> damage</span>
          {showCombined && <span><span style={{ color: COMBO_COLOR }}>■</span> with combos</span>}
        </span>
      </div>
      {killSpeed && CLOCK_TURNS.filter((t) => t <= killSpeed.horizon).map((t) => (
        <ClockRow key={t} turn={t} damage={share(killSpeed.by_turn, t)}
          combined={showCombined ? share(comboClock.by_turn, t) : null} />
      ))}
      {killSpeed?.text && (
        <div style={{ fontSize: 10.5, color: '#a8a29e', lineHeight: 1.45, marginTop: 4 }}>{killSpeed.text}</div>
      )}
      {comboClock?.text && (
        <div style={{ fontSize: 10.5, color: '#fdba74', lineHeight: 1.45, marginTop: 3 }}>{comboClock.text}</div>
      )}
      {timed.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ fontSize: 10.5, color: '#78716c', cursor: 'pointer', userSelect: 'none' }}>
            <Term def={TERMS.combo_clock}>Each combo on the clock</Term> ({timed.length} timed{untimed.length ? `, ${untimed.length} not timed` : ''})
          </summary>
          <div style={{ marginTop: 5 }}>
            {timed.slice(0, 6).map((c, i) => (
              <div key={i} style={{ marginBottom: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: '#e7e5e4', lineHeight: 1.4 }}>
                  <ComboSpark byTurn={c.by_turn} />
                  <span style={{ flex: 1 }}>{c.cards.join(' + ')}</span>
                  <span style={{ fontSize: 10, color: '#fdba74', whiteSpace: 'nowrap' }}>
                    {c.turn_50 ? `half of games by T${c.turn_50}` : c.turn_25 ? `a quarter by T${c.turn_25}` : 'rarely assembled'}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: '#78716c', marginLeft: 46 }}>
                  {COMBO_KIND[c.kind] || c.kind} · {c.mana_value} mana to go off
                  {c.tutors?.length ? ` · ${c.tutors.length} tutor${c.tutors.length > 1 ? 's' : ''} can find a piece` : ''}
                  {c.deterministic === false ? ' · ⚠ not deterministic' : ''}
                </div>
                {c.assumes?.length > 0 && (
                  <div style={{ fontSize: 10, color: '#a8a29e', marginLeft: 46 }}>assumes: {c.assumes.join('; ')}</div>
                )}
              </div>
            ))}
            {untimed.slice(0, 4).map((c, i) => (
              <div key={`u${i}`} style={{ fontSize: 10, color: '#78716c', lineHeight: 1.4, marginBottom: 3 }}>
                {c.cards.join(' + ')} — not timed: {c.not_timed}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

// The player's own bracket beside ours. The rules verdict comes from the engine
// (`bracket_rules`: the official Game Changer limits and two-card infinite combos, per
// bracket), so picking a different bracket never re-simulates and never re-implements the
// rules here. A disallowed bracket is said plainly; otherwise the measured one is compared.
const BRACKET_COLORS = { 1: '#4ade80', 2: '#a3e635', 3: '#eab308', 4: '#f97316', 5: '#ef4444' }

function StatedBracket({ stated, measured, rules, onChange }) {
  const verdict = (() => {
    if (!stated) return null
    const rule = rules?.by_bracket?.[String(stated)]
    if (rule && !rule.allowed) {
      const lowest = [1, 2, 3, 4, 5].find((b) => rules.by_bracket[String(b)]?.allowed)
      return {
        color: '#ef4444',
        head: `The official rules don't allow Bracket ${stated} for this list`,
        body: `${rule.reasons.join('; ')}.${lowest ? ` The lowest bracket its cards allow is ${lowest}.` : ''}`,
      }
    }
    if (!measured) return null
    if (stated === measured) {
      return { color: '#4ade80', head: `We agree: Bracket ${stated}`, body: 'Your bracket and the measured one match.' }
    }
    if (measured > stated) {
      return {
        color: '#f97316',
        head: `Plays above your Bracket ${stated}: we measure Bracket ${measured}`,
        body: `Expect it to outpace most Bracket ${stated} tables; say so in the pre-game talk, or see the axes below for what pushes it up.`,
      }
    }
    return {
      color: '#38bdf8',
      head: `Plays below your Bracket ${stated}: we measure Bracket ${measured}`,
      body: `It may struggle at a Bracket ${stated} table; the weaknesses below say where.`,
    }
  })()
  const notChecked = stated && stated <= 2 && rules && !rules.combos_checked
  return (
    <div style={{ margin: '-2px 0 10px', padding: '7px 10px', borderRadius: 8, background: '#1c1917', border: '1px solid #292524' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11.5, color: '#a8a29e', marginRight: 2 }}>
          <Term def="The bracket YOU (or the deck's builder) call this deck. It never changes the measurement; it is shown beside ours so a mismatch is visible before you sit down at a table.">Your bracket</Term>
        </span>
        {[null, 1, 2, 3, 4, 5].map((b) => {
          const on = stated === b
          const c = b ? BRACKET_COLORS[b] : '#78716c'
          return (
            <button key={b ?? 'none'} type="button" onClick={() => onChange(b)}
              title={b ? `${BRACKET_TERMS[b]?.label || ''}` : 'Not set'}
              style={{
                fontSize: 11, fontWeight: on ? 800 : 500, minWidth: 26, padding: '1px 7px', borderRadius: 12,
                cursor: 'pointer', fontFamily: 'inherit',
                background: on ? `${c}33` : 'transparent', color: on ? c : '#78716c',
                border: `1px solid ${on ? c : '#44403c'}`,
              }}>
              {b ?? '—'}
            </button>
          )
        })}
      </div>
      {verdict && (
        <div style={{ marginTop: 6, fontSize: 11, lineHeight: 1.45 }}>
          <div style={{ color: verdict.color, fontWeight: 700 }}>{verdict.head}</div>
          <div style={{ color: '#a8a29e' }}>{verdict.body}</div>
        </div>
      )}
      {notChecked && (
        <div style={{ marginTop: 3, fontSize: 10, color: '#78716c' }}>
          Two-card infinite combos were not checked (Commander Spellbook unreachable).
        </div>
      )}
    </div>
  )
}

// Simulation-grounded strength panel (MythGauntlet, Myth Suite C3) — shared by
// the import preview (StepCommander) and the result screen's Measure panel
// (StepDeck), so the two surfaces can't drift. Pure presentation: pass the
// `simulation` object exactly as the API returns it
// ({engine_version, power_profile, unresolved}).
// `statedBracket` / `onStatedBracketChange`: the player's own bracket for this list. When the
// handler is passed, a "Your bracket" picker sits under the measured badge; without it (a
// caller that has nowhere to store the answer) nothing is shown.
export default function SimStrengthPanel({ simulation, statedBracket = null, onStatedBracketChange = null }) {
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
  // The engine serialises this as `insight.why` (mythgauntlet server._insight_block); reading
  // only `axis_why` meant every engine-written line fell back to the hand-rolled text below.
  const why = insight?.why || insight?.axis_why || {}
  // "2 removal, 6 counters, 0 wipes; breadth 2/3" -- the same breakdown the CLI has always
  // shown, now reaching the panel instead of just a bare 0-100 score.
  const interactionDetail = why.Interaction || (pp.interaction_answers != null && (
    <>
      {pp.interaction_answers} answer{pp.interaction_answers === 1 ? '' : 's'}
      {pp.interaction_effective_answers != null
        ? ` (${pp.interaction_effective_answers.toFixed(1)} castable-weighted)` : ''}
      {pp.interaction_spot_removal != null && (
        <> — {pp.interaction_spot_removal} removal, {pp.interaction_counterspells} counters,{' '}
          {pp.interaction_board_wipes} wipes
          {pp.interaction_noncreature_answers ? `, ${pp.interaction_noncreature_answers} artifact/enchantment answers` : ''};
          breadth {pp.interaction_breadth}/{pp.interaction_breadth_max ?? 3}</>
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
              <Term def="WotC's official 1-5 power-level system for Commander matchmaking. Placed here from the deck's measured speed and strength (consistency, kill speed, resilience, interaction, fast mana, tutors, curve, mana base), calibrated against brackets real players assigned their decks. The official rules (Game Changers, combos, mass land denial, extra turns) set the minimum it can be, never a cap.">Simulated bracket</Term>
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
      <Dials dials={simulation.dials} />
      {onStatedBracketChange && (
        <StatedBracket stated={statedBracket} measured={pp.bracket_estimate}
          rules={simulation.bracket_rules} onChange={onStatedBracketChange} />
      )}
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
      {/* Since 2026-10-18 the bracket is placed by measured speed + strength, with the official
          gates as floors (ratings/strength_model.py). `plays_up` marks a deck whose strength
          score sits right below the next bracket's cut. Amber, not red: this describes
          uncertainty, not a defect, the same convention as the manabase panel's
          `ramp-dependent`. */}
      {pp.bracket_plays_up && (
        <div
          title={'The bracket is placed from measured speed and strength (with the official '
            + 'Game Changer, combo, land-denial and extra-turn rules as floors). This deck’s '
            + 'strength score sits right at the line to the next bracket, so it may play up at '
            + 'some tables. Read the axes below and mention it in your pre-game talk.'}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10,
            padding: '6px 10px', borderRadius: 8,
            background: '#1c1408', border: '1px solid #a16207', cursor: 'help',
          }}
        >
          <span style={{ fontSize: 13, color: '#fde047' }}>↗</span>
          <span style={{ fontSize: 11.5, color: '#fde047', lineHeight: 1.45 }}>
            <strong>Sits on the Bracket {pp.bracket_estimate} / {pp.bracket_estimate + 1} line.</strong>{' '}
            Its measured strength is right at the boundary, so it may play like a{' '}
            {pp.bracket_estimate + 1} at some tables.
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
      <TableFeel pp={pp} detail={why['Table feel']} />
      <Denial denial={simulation.denial} />
      <WeakAgainst exposure={simulation.exposure} />
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
      <KillClock killSpeed={simulation.kill_speed} comboClock={simulation.combo_clock} />
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
