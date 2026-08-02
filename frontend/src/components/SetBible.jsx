import { useState } from 'react'

/**
 * The finished deck's SET BIBLE — the world its cards are printed in.
 *
 * Every themed build already runs an LLM pass that designs this (themer's
 * build_creative_brief + build_color_factions) and persists the whole thing into
 * deck.json as `world_bible`. Until now the only place it was ever rendered was
 * ThemePreview, which is mounted solely in the Theme step — so you saw your world
 * BEFORE the deck existed and never again. This shows it on the deck itself, where
 * the cards it explains actually are. Nothing here is generated: it is a read of
 * data the deck already carries, so it lights up every deck built since the brief
 * pipeline landed.
 */

// MTG colour identity → the chip colours used elsewhere in the app (StepDeck's
// colour-pip row), so a faction reads as "the white one" at a glance.
const COLOR_META = {
  W: { name: 'White', bg: '#3a3526', fg: '#f5e6c8', dot: '#f5e6c8' },
  U: { name: 'Blue',  bg: '#0c2748', fg: '#7dd3fc', dot: '#60a5fa' },
  B: { name: 'Black', bg: '#2b2735', fg: '#c4b5fd', dot: '#a78bfa' },
  R: { name: 'Red',   bg: '#3a1414', fg: '#fca5a5', dot: '#f87171' },
  G: { name: 'Green', bg: '#11331c', fg: '#86efac', dot: '#4ade80' },
  C: { name: 'Colorless', bg: '#1c1917', fg: '#a8a29e', dot: '#a8a29e' },
}
const COLOR_ORDER = ['W', 'U', 'B', 'R', 'G', 'C']

const MECHANIC_LABELS = {
  removal: 'Removal',
  draw:    'Card draw',
  ramp:    'Ramp',
  tokens:  'Tokens',
  counter: 'Counterspells',
}

const label = {
  fontSize: 10.5, fontWeight: 700, color: '#a8a29e', letterSpacing: '0.09em',
  textTransform: 'uppercase', marginBottom: 7,
}

// The theme-expansion prompt asks the model to "fill in the brackets", and it often
// returns them, so some stored bibles carry a literal "[A world of ...]". themer's
// _unwrap_placeholder fixes this at the source for new decks; this cleans the ones
// already on disk at read time. Only a pair wrapping the WHOLE value is removed.
function clean(v) {
  let s = String(v ?? '').trim()
  for (let i = 0; i < 3; i++) {
    // A bracket pair closing the string, opened after the last "]" — covers both
    // "[A world of ...]" and _expand_theme's "<your brief> — [A world of ...]",
    // where it joined the seed to a still-bracketed description.
    const m = s.endsWith(']') ? s.match(/^([^\]]*?)\[([^\]]+)\]$/) : null
    if (m && m[2].trim()) s = (m[1] + m[2]).trim()
    else break
  }
  return s.replace(/\s+—\s*$/, '').trim()
}
const cleanAll = a => (Array.isArray(a) ? a.map(clean).filter(Boolean) : [])

function Chips({ items, tone = '#78716c' }) {
  if (!items?.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
      {items.map((m, i) => (
        <span key={`${m}-${i}`} style={{
          fontSize: 11.5, padding: '2px 9px', borderRadius: 20,
          background: '#12100f', border: `1px solid ${tone}44`, color: '#d6d3d1',
        }}>{m}</span>
      ))}
    </div>
  )
}

function Faction({ code, f }) {
  const meta = COLOR_META[code] || COLOR_META.C
  return (
    <div style={{
      background: '#0c0a09', border: '1px solid #292524', borderRadius: 10,
      padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{
          width: 16, height: 16, borderRadius: '50%', background: meta.bg,
          border: `1.5px solid ${meta.dot}`, flexShrink: 0,
        }} />
        <span style={{ fontSize: 13.5, fontWeight: 700, color: meta.fg }}>
          {clean(f.name) || meta.name}
        </span>
        <span style={{ fontSize: 10.5, color: '#57534e', marginLeft: 'auto' }}>{meta.name}</span>
      </div>
      {f.people && (
        <div style={{ fontSize: 12, color: '#d6d3d1', lineHeight: 1.5 }}>{clean(f.people)}</div>
      )}
      {f.philosophy && (
        <div style={{ fontSize: 12, color: '#a8a29e', lineHeight: 1.5, fontStyle: 'italic' }}>
          “{clean(f.philosophy)}”
        </div>
      )}
      {f.aesthetic && (
        <div style={{ fontSize: 11.5, color: '#78716c', lineHeight: 1.5 }}>{clean(f.aesthetic)}</div>
      )}
      <Chips items={cleanAll(f.motifs)} tone={meta.dot} />
    </div>
  )
}

export default function SetBible({ bible, theme }) {
  const [open, setOpen] = useState(false)
  if (!bible || !bible.world) return null

  const factions = bible.color_factions || {}
  const codes = COLOR_ORDER.filter(c => factions[c])
  const mech = bible.mechanic_flavor || {}
  const mechKeys = Object.keys(MECHANIC_LABELS).filter(k => mech[k])

  return (
    <div style={{
      marginBottom: 20, borderRadius: 12, overflow: 'hidden',
      background: '#0e0b16', border: '1px solid #3b2f63',
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 16px', background: 'none', border: 'none', cursor: 'pointer',
          fontFamily: 'inherit', textAlign: 'left', color: '#e7e5e4',
        }}
      >
        <span style={{ fontSize: 15 }}>📖</span>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: '#c4b5fd' }}>Set Bible</span>
        <span style={{
          fontSize: 11.5, color: '#78716c', overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0,
        }}>
          — {open ? 'the world these cards are printed in' : clean(bible.world)}
        </span>
        <span style={{ fontSize: 11, color: '#57534e', flexShrink: 0 }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <div style={label}>The world</div>
            <div style={{ fontSize: 13, color: '#e7e5e4', lineHeight: 1.6 }}>{clean(bible.world)}</div>
            {theme && (
              <div style={{ fontSize: 11, color: '#57534e', marginTop: 6, lineHeight: 1.5 }}>
                Grown from your brief: “{theme}”
              </div>
            )}
          </div>

          {bible.lore && (
            <div style={{
              padding: '11px 14px', borderLeft: '2px solid #7c3aed', background: '#12101c',
              borderRadius: '0 8px 8px 0',
            }}>
              <div style={{ ...label, marginBottom: 5 }}>Lore</div>
              <div style={{ fontSize: 12.5, color: '#d6d3d1', lineHeight: 1.6 }}>{clean(bible.lore)}</div>
            </div>
          )}

          {codes.length > 0 && (
            <div>
              <div style={label}>
                Factions <span style={{ color: '#57534e', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
                  — who each colour is in this world
                </span>
              </div>
              <div style={{
                display: 'grid', gap: 10,
                gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
              }}>
                {codes.map(c => <Faction key={c} code={c} f={factions[c] || {}} />)}
              </div>
            </div>
          )}

          {mechKeys.length > 0 && (
            <div>
              <div style={label}>
                How magic works here <span style={{ color: '#57534e', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
                  — the in-world reading of each effect
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {mechKeys.map(k => (
                  <div key={k} style={{ display: 'flex', gap: 10, fontSize: 12, lineHeight: 1.5 }}>
                    <span style={{ color: '#a78bfa', minWidth: 96, flexShrink: 0, fontWeight: 600 }}>
                      {MECHANIC_LABELS[k]}
                    </span>
                    <span style={{ color: '#d6d3d1' }}>{clean(mech[k])}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {bible.zones?.length > 0 && (
            <div>
              <div style={label}>Places</div>
              <Chips items={cleanAll(bible.zones)} tone="#7c3aed" />
            </div>
          )}

          {(bible.must_include?.length > 0 || bible.signature_details?.length > 0) && (
            <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
              {bible.must_include?.length > 0 && (
                <div>
                  <div style={label}>
                    You asked for <span style={{ color: '#57534e', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
                      — kept verbatim
                    </span>
                  </div>
                  <Chips items={cleanAll(bible.must_include)} tone="#16a34a" />
                </div>
              )}
              {bible.signature_details?.length > 0 && (
                <div>
                  <div style={label}>
                    The set invented <span style={{ color: '#57534e', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
                      — {bible.creativity || 'balanced'}
                    </span>
                  </div>
                  <Chips items={cleanAll(bible.signature_details)} tone="#ca8a04" />
                </div>
              )}
            </div>
          )}

          {bible.palette && (
            <div>
              <div style={label}>Palette</div>
              <div style={{ fontSize: 12, color: '#d6d3d1', lineHeight: 1.5 }}>{clean(bible.palette)}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
