// The hover edit bar shared by the image views (binder grid, art tiles): − / count / + /
// choose-printing / remove. Positioned over the bottom of its (relative) parent.

const c = {
  gold:   '#eab308',
  dim:    '#a8a29e',
  card:   '#1c1917',
  border: '#292524',
}

export default function CollectionEditBar({ row, busy, onSetCount, onRemove, onPickPrinting }) {
  const ctl = (extra = {}) => ({
    padding: '1px 7px', borderRadius: 6, fontSize: 12, background: c.card,
    border: `1px solid ${c.border}`, color: c.dim, fontFamily: 'inherit',
    cursor: busy ? 'wait' : 'pointer', ...extra,
  })
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0,
                  background: 'rgba(0,0,0,0.86)', padding: 6, display: 'flex',
                  gap: 4, alignItems: 'center', justifyContent: 'center' }}>
      <button disabled={busy} title="One fewer" style={ctl()}
        onClick={() => onSetCount && onSetCount(row, row.count - 1)}>−</button>
      <span style={{ color: c.gold, fontWeight: 700, minWidth: 18, textAlign: 'center',
                     fontSize: 12 }}>{row.count}</span>
      <button disabled={busy} title="One more" style={ctl()}
        onClick={() => onSetCount && onSetCount(row, row.count + 1)}>+</button>
      {onPickPrinting && (
        <button disabled={busy} title="Choose printing" style={ctl()}
          onClick={() => onPickPrinting(row)}>🖨</button>
      )}
      <button disabled={busy} title="Remove" style={ctl({ color: '#f87171' })}
        onClick={() => onRemove && onRemove(row)}>✕</button>
    </div>
  )
}
