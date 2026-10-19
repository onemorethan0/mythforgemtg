import { useEffect, useRef, useState } from 'react'
import { synergyRows } from '../utils/deckBreakdown'

// Charts for the Deck Mentor's own measurements (engine /breakdown via Forge's
// /api/deck/{id}/breakdown): role cards vs a typical card target, what the deck's
// interaction can answer, and colour sources. The block is the mentor's tool output
// verbatim, so these bars can never disagree with a mentor answer about the same deck.
// The parent gets the whole block through `onData` (StepDeck groups cards by role from it).

const ROLE_LABELS = {
  ramp: 'Ramp', draw: 'Card draw', removal: 'Creature removal',
  noncreature_removal: 'Other removal', wipe: 'Board wipes', counterspell: 'Counterspells',
  tutor: 'Tutors', finisher: 'Finishers',
}
const roleLabel = r => ROLE_LABELS[r] || r.replace(/_/g, ' ')
const ROLE_RANK = Object.keys(ROLE_LABELS)
const byRoleOrder = (a, b) => {
  const ra = ROLE_RANK.indexOf(a.role), rb = ROLE_RANK.indexOf(b.role)
  return (ra < 0 ? 99 : ra) - (rb < 0 ? 99 : rb) || a.role.localeCompare(b.role)
}

const ANSWER_TYPES = ['creature', 'artifact', 'enchantment', 'planeswalker', 'land', 'spell']
const cap = s => s.charAt(0).toUpperCase() + s.slice(1)

const SWATCH = { W: '#f8f6d8', U: '#0e68ab', B: '#4b3f48', R: '#d3202a', G: '#00733e', C: '#a8a29e' }

const sectionTitle = { fontSize: 12, fontWeight: 700, color: '#f5f5f4', marginBottom: 10 }
const rowHead = { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3, fontSize: 12 }
const track = { height: 8, background: '#292524', borderRadius: 4, position: 'relative', marginBottom: 9 }
const footnote = { fontSize: 11, color: '#78716c', marginTop: 6, lineHeight: 1.4 }
const pct = (n, max) => `${Math.max(0, Math.min(100, (n / max) * 100))}%`

function RoleChart({ roles }) {
  const rows = [...(roles.rows || [])].sort(byRoleOrder)
  const max = Math.max(1, ...rows.map(r => Math.max(r.cards, r.card_target)))
  return (
    <div>
      <div style={sectionTitle}>Roles (cards vs typical)</div>
      {rows.map(r => {
        const short = r.short_by > 0
        return (
          <div key={r.role}>
            <div style={rowHead}>
              <span style={{ color: '#a8a29e' }}>
                {roleLabel(r.role)}
                {r.role === roles.most_under_supplied && (
                  <span style={{ marginLeft: 6, fontSize: 10, padding: '1px 6px', borderRadius: 4,
                    background: '#450a0a', color: '#fca5a5', fontWeight: 700 }}>biggest gap</span>
                )}
              </span>
              <span style={{ color: short ? '#f59e0b' : '#f5f5f4', fontWeight: 700 }}>
                {r.cards} <span style={{ color: '#78716c', fontWeight: 400 }}>/ {r.card_target}</span>
              </span>
            </div>
            <div style={track} title={short ? `${r.short_by} short of a typical deck` : 'At or above a typical deck'}>
              <div style={{ position: 'absolute', left: 0, top: 0, height: 8, borderRadius: 4,
                width: pct(r.cards, max), background: short ? '#f59e0b' : '#22c55e', transition: 'width 0.5s' }} />
              <div style={{ position: 'absolute', top: -2, height: 12, width: 2, background: '#f5f5f4',
                left: `calc(${pct(r.card_target, max)} - 1px)` }} />
            </div>
          </div>
        )
      })}
      {(roles.not_applicable || []).map(n => (
        <div key={n.role} title={n.note} style={{ fontSize: 11, color: '#57534e', marginTop: 2 }}>
          {roleLabel(n.role)}: {n.cards} — not a gap for this deck
        </div>
      ))}
      <div style={footnote}>White tick = what a typical deck runs. A card can fill several roles.</div>
    </div>
  )
}

function AnswerChart({ removal }) {
  const counts = removal.counts_by_type || {}
  const na = removal.not_applicable_types || {}
  const types = ANSWER_TYPES.filter(t => counts[t] && !na[t])
  const max = Math.max(1, ...types.map(t => counts[t].answers))
  return (
    <div>
      <div style={sectionTitle}>What your removal can answer</div>
      {types.map(t => {
        const { answers, unrestricted } = counts[t]
        const names = (removal.answers_by_type || {})[t] || []
        return (
          <div key={t}>
            <div style={rowHead}>
              <span style={{ color: '#a8a29e' }}>{cap(t)}</span>
              <span style={{ color: answers ? '#f5f5f4' : '#ef4444', fontWeight: 700 }}>
                {answers}{answers === 0 && <span style={{ fontWeight: 400 }}> — no answer</span>}
              </span>
            </div>
            <div style={track} title={names.join(', ') || 'Nothing in the deck answers this'}>
              <div style={{ position: 'absolute', left: 0, top: 0, height: 8, borderRadius: '4px 0 0 4px',
                width: pct(unrestricted, max), background: '#ca8a04' }} />
              <div style={{ position: 'absolute', top: 0, height: 8, left: pct(unrestricted, max),
                width: pct(answers - unrestricted, max), background: '#ca8a0455' }} />
            </div>
          </div>
        )
      })}
      {Object.entries(na).map(([t, note]) => (
        <div key={t} title={note} style={{ fontSize: 11, color: '#57534e', marginTop: 2 }}>
          {cap(t)}: not expected in these colours
        </div>
      ))}
      <div style={footnote}>
        {removal.exile_count ?? 0} exile · {removal.instant_speed_count ?? 0} instant-speed ·
        solid = no targeting restriction, faded = restricted (e.g. “with flying”). Hover a bar for the cards.
      </div>
    </div>
  )
}

function ManaChart({ manabase, curve, identity }) {
  // The engine counts every colour a land can make (a five-colour land is a "U source" in a
  // Mardu deck); only the command zone's colours are castable needs, so the rest is noise.
  const sources = Object.entries(manabase.sources || {})
    .filter(([c]) => !identity.length || identity.includes(c))
    .sort((a, b) => 'WUBRGC'.indexOf(a[0]) - 'WUBRGC'.indexOf(b[0]))
  const max = Math.max(1, ...sources.map(([, n]) => n))
  return (
    <div>
      <div style={sectionTitle}>Colour sources</div>
      {sources.map(([c, n]) => (
        <div key={c} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 7, fontSize: 12 }}>
          <span style={{ width: 12, height: 12, borderRadius: '50%', flexShrink: 0,
            background: SWATCH[c] || SWATCH.C, border: '1px solid #44403c' }} />
          <span style={{ width: 12, color: '#a8a29e' }}>{c}</span>
          <div style={{ ...track, flex: 1, marginBottom: 0 }}>
            <div style={{ position: 'absolute', left: 0, top: 0, height: 8, borderRadius: 4,
              width: pct(n, max), background: SWATCH[c] || SWATCH.C }} />
          </div>
          <span style={{ width: 22, textAlign: 'right', color: '#f5f5f4', fontWeight: 700 }}>{n}</span>
        </div>
      ))}
      {(manabase.worst_colors || []).map(w => (
        <div key={`${w.color}-${w.turn}`} style={{ fontSize: 12, marginTop: 4,
          color: w.have < w.need ? '#f59e0b' : '#a8a29e' }}>
          {w.color}: {w.have} of {w.need} sources to cast {w.example} on turn {w.turn} ({Math.round(w.probability * 100)}%)
        </div>
      ))}
      {curve && (
        <div style={footnote}>
          Curve: avg MV {curve.average_mana_value} · {curve.nonland_count} spells · {curve.land_count} lands
        </div>
      )}
    </div>
  )
}

function SynergyList({ rows }) {
  const badge = { marginLeft: 6, fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 700 }
  return (
    <div>
      <div style={sectionTitle}>Commander synergy</div>
      {rows.map(r => (
        <div key={r.name} style={{ marginBottom: 8, fontSize: 12 }}>
          <div>
            <span style={{ color: '#f5f5f4', fontWeight: 700 }}>{r.name}</span>
            {r.oneSided && <span style={{ ...badge, background: '#052e16', color: '#86efac' }}>one-sided wipe</span>}
            {r.treasure > 0 && <span style={{ ...badge, background: '#422006', color: '#fcd34d' }}>+{r.treasure} Treasure</span>}
          </div>
          <div style={{ color: '#a8a29e', lineHeight: 1.4 }}>{r.reason}</div>
        </div>
      ))}
    </div>
  )
}

async function fetchBreakdown(jobId, refresh) {
  try {
    const res = await fetch(`/api/deck/${jobId}/breakdown${refresh ? '?refresh=true' : ''}`, { method: 'POST' })
    let body = null
    try { body = await res.json() } catch { /* non-JSON error page */ }
    return res.ok ? { data: body } : { error: body?.detail || res.statusText }
  } catch (e) {
    return { error: String(e.message || e) }
  }
}

export default function DeckBreakdownPanel({ jobId, initial, onData }) {
  const [data, setData] = useState(initial || null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(true)
  const alive = useRef(true)

  // `onData` is a state setter in StepDeck (stable), so it is deliberately not a dependency:
  // a fresh callback must never trigger a re-measure.
  const apply = (r) => {
    setLoading(false)
    if (r.error) { setError(r.error); return }
    setError(null); setData(r.data); onData?.(r.data)
  }

  useEffect(() => {
    let active = true
    alive.current = true
    fetchBreakdown(jobId, false).then(r => { if (active) apply(r) })
    return () => { active = false; alive.current = false }   // a reply after unmount / jobId change is dropped
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  const remeasure = () => {
    setLoading(true)
    fetchBreakdown(jobId, true).then(r => { if (alive.current) apply(r) })
  }

  const btn = { background: '#1c1917', border: '1px solid #292524', borderRadius: 6, padding: '4px 10px',
    color: '#a8a29e', fontSize: 11, cursor: 'pointer', fontFamily: 'inherit' }

  const synergy = synergyRows(data?.cards)

  return (
    <div style={{ background: '#0c0a09', border: '1px solid #292524', borderRadius: 10, padding: 14, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button onClick={() => setOpen(o => !o)} aria-expanded={open}
          style={{ ...btn, background: 'none', border: 'none', padding: 0, color: '#f5f5f4', fontSize: 13, fontWeight: 700 }}>
          {open ? '▾' : '▸'} 📊 Deck Breakdown
        </button>
        <span style={{ fontSize: 11, color: '#78716c', flex: 1 }}>The numbers the Deck Mentor answers from</span>
        {data?.computed_at && !loading && (
          <span style={{ fontSize: 11, color: '#57534e' }}>measured {data.computed_at.replace('T', ' ')}</span>
        )}
        <button onClick={remeasure} disabled={loading} style={{ ...btn, opacity: loading ? 0.6 : 1 }}
          title="Measure again (the engine's role tagger may have improved since)">
          {loading ? '⏳ Measuring…' : '↻ Re-measure'}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 12 }}>
          {error && <div style={{ fontSize: 12, color: '#fca5a5', marginBottom: 8 }}>⚠ {error}</div>}
          {!data && loading && <div style={{ fontSize: 12, color: '#78716c' }}>Measuring roles…</div>}
          {data && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 22 }}>
              {data.roles && <RoleChart roles={data.roles} />}
              {data.removal && <AnswerChart removal={data.removal} />}
              {data.manabase && <ManaChart manabase={data.manabase} curve={data.curve}
                identity={[...new Set((data.commanders || []).flatMap(c => c.color_identity || []))]} />}
              {synergy.length > 0 && <SynergyList rows={synergy} />}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
