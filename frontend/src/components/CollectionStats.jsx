import { useState } from 'react'

// Collection insights panel: value, colour spread, mana curve, type/rarity/set
// breakdown and the most valuable cards. Fed by GET /api/collection/stats.
// Every segment is a filter shortcut — clicking a colour, a curve bucket, a type or a
// rarity asks the parent to narrow the list to it.

const c = {
  gold:   '#eab308',
  green:  '#4ade80',
  dim:    '#a8a29e',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
  text:   '#f5f5f4',
}

const MANA = { W: '#f8f0d8', U: '#4a90d9', B: '#5b5254', R: '#d94a4a', G: '#4aa563',
               Multicolor: '#c9a227', Colorless: '#8a8a8a' }

// Dark chips need light text; the pale ones need dark.
const DARK_TEXT_ON = new Set(['W', 'Multicolor'])

const money = v => Number(v || 0).toLocaleString(undefined, {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})

const heading = {
  fontSize: 12, fontWeight: 700, color: c.dim, letterSpacing: '0.06em',
  textTransform: 'uppercase', marginBottom: 10,
}
const panel = {
  background: c.panel, border: `1px solid ${c.border}`, borderRadius: 10, padding: 14,
}

// distinct-proportional row used by both Types and Rarities.
function BreakdownList({ title, rows, labelOf, onPick }) {
  const max = Math.max(1, ...rows.map(r => r.distinct))
  return (
    <div>
      <div style={heading}>{title}</div>
      {rows.length === 0 && <div style={{ fontSize: 12, color: c.faint }}>Nothing yet.</div>}
      {rows.map(r => (
        <div key={r.key} onClick={() => onPick && onPick(r.key)}
          style={{ marginBottom: 8, cursor: onPick ? 'pointer' : 'default' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 12, color: c.text }}>{labelOf(r)}</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: c.gold }}>{r.distinct}</span>
          </div>
          {/* the bar belongs UNDER the row, so it can't fight the label for width */}
          <div style={{ height: 4, marginTop: 4, background: c.border, borderRadius: 2 }}>
            <div style={{ height: '100%', width: `${100 * r.distinct / max}%`,
                          background: c.gold, borderRadius: 2 }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export default function CollectionStats({ stats, onFilter }) {
  // Hooks run before any early return — bailing out first would change the hook count
  // between the loading and loaded renders, which React treats as a fatal error.
  const [showSets, setShowSets] = useState(false)
  if (!stats) return null

  const totals    = stats.totals || {}
  const colors    = (stats.colors || []).filter(x => x.distinct > 0)
  const presence  = (stats.color_presence || []).filter(x => x.distinct > 0)
  const types     = stats.types || []
  const rarities  = stats.rarities || []
  const curve     = stats.curve || []
  const sets      = stats.sets || []
  const topValue  = stats.top_value || []
  const maxCurve  = Math.max(1, ...curve.map(b => b.distinct))
  const pick      = crit => onFilter && onFilter(crit)

  return (
    <div style={panel}>
      {/* Headline */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <div style={{ fontSize: 22, fontWeight: 700, color: c.green }}>${money(totals.value)}</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: c.text }}>
          {totals.copies || 0} <span style={{ fontSize: 13, color: c.faint, fontWeight: 400 }}>cards</span>
        </div>
        <div style={{ fontSize: 22, fontWeight: 700, color: c.text }}>
          {totals.distinct || 0} <span style={{ fontSize: 13, color: c.faint, fontWeight: 400 }}>unique</span>
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: c.faint, marginTop: 4 }}>
        {totals.priced || 0} priced · {totals.unpriced || 0} unpriced
        {totals.unresolved > 0 && (
          <span style={{ color: '#f59e0b' }}> · {totals.unresolved} unrecognized</span>
        )}
      </div>

      {/* Colours */}
      <div style={{ marginTop: 20 }}>
        <div style={heading}>Colors</div>
        <div style={{ height: 26, borderRadius: 6, overflow: 'hidden', display: 'flex' }}>
          {colors.map(entry => (
            <div key={entry.key}
              onClick={() => pick({ colors: [entry.key] })}
              title={`${entry.label}: ${entry.distinct} cards, ${entry.copies} copies`}
              style={{
                flexGrow: entry.distinct, flexBasis: 0, background: MANA[entry.key] || c.faint,
                cursor: onFilter ? 'pointer' : 'default', display: 'flex',
                alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
                fontSize: 10, fontWeight: 700,
                color: DARK_TEXT_ON.has(entry.key) ? '#1c1917' : '#f5f5f4',
              }}>
              {entry.distinct}
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8,
                      fontSize: 11, color: c.dim }}>
          {colors.map(entry => (
            <span key={entry.key} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%',
                             background: MANA[entry.key] || c.faint, display: 'inline-block' }} />
              {entry.label} ({entry.distinct})
            </span>
          ))}
        </div>
      </div>

      {/* Colour presence — a DIFFERENT question from the exclusive bucket above: "how much
          white do I actually have access to" has to count a Boros card as white too, not
          hide it behind "Multicolor". Same chip style as BreakdownList below, but this one
          overlaps by design (percentages don't sum to the collection total). */}
      {presence.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={heading}>Colour presence</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {presence.map(entry => (
              <span key={entry.key}
                onClick={() => pick({ color_presence: [entry.key] })}
                title={`${entry.label}: ${entry.distinct} cards with a ${entry.label} pip (incl. multicolor), ${entry.copies} copies`}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5,
                  padding: '4px 10px', borderRadius: 20, background: c.card,
                  border: `1px solid ${c.border}`, cursor: onFilter ? 'pointer' : 'default',
                }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%',
                               background: MANA[entry.key] || c.faint, display: 'inline-block' }} />
                <span style={{ color: c.text }}>{entry.label}</span>
                <span style={{ color: c.gold, fontWeight: 700 }}>{entry.distinct}</span>
              </span>
            ))}
          </div>
          <div style={{ fontSize: 11, color: c.faint, marginTop: 6 }}>
            Counts every card with that colour, including multicolor — not the same as the
            exclusive buckets above.
          </div>
        </div>
      )}

      {/* Mana curve */}
      <div style={{ marginTop: 20 }}>
        <div style={heading}>Mana curve</div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 90 }}>
          {curve.map(b => (
            <div key={b.cmc} style={{ flex: 1, display: 'flex', flexDirection: 'column',
                                      justifyContent: 'flex-end', height: '100%' }}>
              <div
                onClick={() => pick({ cmc_min: b.cmc, cmc_max: b.cmc === 7 ? 99 : b.cmc })}
                title={`MV ${b.label}: ${b.distinct} cards`}
                style={{ height: `${Math.round(100 * b.distinct / maxCurve)}%`, minHeight: 2,
                         background: c.gold, borderRadius: '3px 3px 0 0',
                         cursor: onFilter ? 'pointer' : 'default' }} />
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          {curve.map(b => (
            <div key={b.cmc} style={{ flex: 1, textAlign: 'center', fontSize: 10, color: c.faint }}>
              {b.label}
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: c.faint, marginTop: 6 }}>Lands excluded.</div>
      </div>

      {/* Types + rarities */}
      <div style={{ marginTop: 20, display: 'grid', gap: 14,
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <BreakdownList title="Types" rows={types} labelOf={r => r.key}
          onPick={onFilter ? key => pick({ types: [key] }) : null} />
        <BreakdownList title="Rarities" rows={rarities} labelOf={r => r.label || r.key}
          onPick={onFilter ? key => pick({ rarities: [key] }) : null} />
      </div>

      {/* Most valuable */}
      <div style={{ marginTop: 20 }}>
        <div style={heading}>Most valuable</div>
        {topValue.length === 0 ? (
          <div style={{ fontSize: 12.5, color: c.faint }}>No prices yet.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {topValue.map((item, i) => (
              // name alone is not unique — the same card in two printings is two rows.
              <div key={`${item.name}|${item.set}|${item.cn}|${i}`}
                title={`$${money(item.price)} each`}
                style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
                <span style={{ color: c.faint, minWidth: 16 }}>{i + 1}.</span>
                <span style={{ flex: 1, color: c.text, overflow: 'hidden',
                               textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
                {item.set && (
                  <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
                                 padding: '1px 6px', borderRadius: 4, color: c.dim,
                                 background: c.card, border: `1px solid ${c.border}` }}>
                    {item.set}
                  </span>
                )}
                {item.count > 1 && <span style={{ color: c.faint }}>x{item.count}</span>}
                <span style={{ color: c.green, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                  ${money(item.total)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sets */}
      <div style={{ marginTop: 20 }}>
        <div onClick={() => setShowSets(v => !v)}
          style={{ ...heading, marginBottom: showSets ? 10 : 0, cursor: 'pointer',
                   display: 'flex', justifyContent: 'space-between' }}>
          <span>Sets ({sets.length})</span><span>{showSets ? '▴' : '▾'}</span>
        </div>
        {showSets && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {sets.map(s => (
              <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 10,
                                        fontSize: 12.5 }}>
                <span style={{ flex: 1, color: s.key === '—' ? c.faint : c.text }}>
                  {s.key === '—' ? 'printing unknown' : s.key}
                </span>
                <span style={{ color: c.dim }}>{s.distinct}</span>
                <span style={{ color: c.green, fontVariantNumeric: 'tabular-nums' }}>
                  ${money(s.value)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
