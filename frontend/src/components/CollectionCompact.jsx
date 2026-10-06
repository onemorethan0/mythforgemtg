import { useState } from 'react'
import CardHover from './CardHover'
import { decklistLine, dotColor } from '../utils/collectionView'

// Dense decklist view: one line per owned printing in the exact form the importer reads
// back (`3x Sol Ring (C21) 263 *F*`), flowed into CSS columns. "Copy as text" puts those
// same lines on the clipboard, so what you see is what you copy.

const c = {
  gold:   '#eab308',
  green:  '#4ade80',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  text:   '#f5f5f4',
}

export default function CollectionCompact({ cards, selectMode, selected, onToggleSelect }) {
  const [note, setNote] = useState('')
  const rows = cards || []
  const picked = selected || new Set()

  if (rows.length === 0) {
    return <div style={{ fontSize: 13, color: c.faint, padding: 20, textAlign: 'center' }}>
      Nothing to show.
    </div>
  }

  const copy = async () => {
    const text = rows.map(decklistLine).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setNote(`Copied ${rows.length} line${rows.length === 1 ? '' : 's'}.`)
    } catch {
      setNote('Copy was blocked by the browser — select the lines and copy them by hand.')
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <button onClick={copy}
          style={{ padding: '3px 10px', borderRadius: 6, fontSize: 12, background: c.card,
                   border: `1px solid ${c.border}`, color: c.gold, cursor: 'pointer',
                   fontFamily: 'inherit' }}>
          Copy as text
        </button>
        {note && <span role="status" style={{ fontSize: 12, color: c.faint }}>{note}</span>}
      </div>

      <div style={{ columns: '280px', columnGap: 20 }}>
        {rows.map(row => {
          const key = row.row_id
          const isSel = picked.has(key)
          const dot = dotColor(row)
          return (
            <div key={key}
              onClick={selectMode ? () => onToggleSelect && onToggleSelect(row) : undefined}
              style={{ display: 'flex', alignItems: 'center', gap: 6, breakInside: 'avoid',
                       padding: '1px 4px', fontSize: 12.5, lineHeight: '20px',
                       fontFamily: 'ui-monospace, Consolas, monospace', color: c.text,
                       cursor: selectMode ? 'pointer' : 'default', borderRadius: 4,
                       border: `1px solid ${isSel ? c.gold : 'transparent'}` }}>
              {selectMode && (
                <input type="checkbox" checked={isSel} readOnly
                  style={{ margin: 0, pointerEvents: 'none' }} />
              )}
              <span style={{ flex: '0 0 auto', width: 9, height: 9, borderRadius: '50%',
                             background: dot || 'transparent',
                             border: dot ? 'none' : `1px solid ${c.faint}` }} />
              <CardHover name={row.name}
                style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden',
                         textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {decklistLine(row)}
              </CardHover>
              {typeof row.price === 'number' && (
                <span style={{ flex: '0 0 auto', marginLeft: 'auto', color: c.green, fontSize: 11.5 }}>
                  ${row.price.toFixed(2)}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
