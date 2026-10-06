import { splitByGroup, groupValueLabel } from '../utils/collectionView'

// Grouped rendering for every collection view except stacks. The page's rows arrive in
// server order (already ordered by group), so splitting on `row.group` keeps that order;
// each header's totals are the server's whole-set `groups`, never counts of this page.
// `render(rows)` draws one group's rows with whichever view is active.
//
// Props: { cards, groups, collapsed: [keys], onToggleGroup(key), render(rows),
//          onShowAll?: () => void   // offered on a group the page cut through
//          onAddPrinting?: (groupLabel) => void }   // "+ printing" header action, when given

const c = {
  gold:   '#eab308',
  green:  '#4ade80',
  dim:    '#a8a29e',
  faint:  '#78716c',
  amber:  '#fbbf24',
  card:   '#1c1917',
  border: '#292524',
  text:   '#f5f5f4',
}

const smallBtn = extra => ({
  background: 'none', border: `1px solid ${c.border}`, borderRadius: 6, cursor: 'pointer',
  fontFamily: 'inherit', fontSize: 12, padding: '2px 8px', color: c.dim, ...extra,
})

export default function CollectionGroups({ cards, groups, collapsed, onToggleGroup, render,
                                           onShowAll, onAddPrinting }) {
  const sections = splitByGroup(cards, groups)
  if (sections.length === 1 && sections[0].headerless) return render(sections[0].pageRows)

  const shut = new Set(collapsed || [])
  const seen = new Set(sections.map(s => s.key))
  const unseen = (groups || []).filter(g => !seen.has(g.key)).length

  return (
    <div>
      {sections.map(sec => {
        const isShut = shut.has(sec.key)
        const body = `coll-group-${sec.key}`
        return (
          <section key={sec.key} style={{ marginBottom: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
                          borderBottom: `1px solid ${c.border}`, paddingBottom: 4 }}>
              <button onClick={() => onToggleGroup && onToggleGroup(sec.key)}
                aria-expanded={!isShut} aria-controls={body}
                title={isShut ? 'Expand group' : 'Collapse group'}
                style={{ flex: '1 1 auto', display: 'flex', alignItems: 'baseline', gap: 10,
                         background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
                         fontFamily: 'inherit', padding: '2px 0', minWidth: 0 }}>
                <span aria-hidden="true" style={{ color: c.faint, fontSize: 11, width: 10 }}>
                  {isShut ? '▸' : '▾'}
                </span>
                <span style={{ color: c.gold, fontWeight: 700, fontSize: 14, overflow: 'hidden',
                               textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sec.label}</span>
                <span style={{ color: c.dim, fontSize: 12, whiteSpace: 'nowrap' }}>
                  {sec.rows} printing{sec.rows === 1 ? '' : 's'} · {sec.cards} card{sec.cards === 1 ? '' : 's'}
                </span>
                <span style={{ color: c.green, fontSize: 12, fontWeight: 700, marginLeft: 'auto' }}>
                  {groupValueLabel(sec)}
                </span>
              </button>
              {onAddPrinting && (
                <button onClick={() => onAddPrinting(sec.label)} style={smallBtn()}
                  title={`Add another printing of ${sec.label}`}>+ printing</button>
              )}
            </div>
            {!isShut && (
              <div id={body}>
                {render(sec.pageRows)}
                {sec.continues && (
                  <div style={{ fontSize: 12, color: c.amber, marginTop: 8 }}>
                    continues — {sec.pageRows.length} of {sec.rows} shown
                    {onShowAll && (
                      <button onClick={onShowAll} style={smallBtn({ color: c.amber, marginLeft: 8 })}>
                        Show all
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        )
      })}
      {unseen > 0 && (
        <div style={{ fontSize: 12, color: c.amber }}>
          {unseen} more group{unseen === 1 ? '' : 's'} after this page
          {onShowAll && (
            <button onClick={onShowAll} style={smallBtn({ color: c.amber, marginLeft: 8 })}>Show all</button>
          )}
        </div>
      )}
    </div>
  )
}
