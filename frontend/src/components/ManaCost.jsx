const PIP_COLORS = {
  W: { bg: '#fef9c3', color: '#1c1917', border: '#fde68a' },
  U: { bg: '#3b82f6', color: '#fff', border: '#93c5fd' },
  B: { bg: '#1c1917', color: '#d6d3d1', border: '#57534e' },
  R: { bg: '#dc2626', color: '#fff', border: '#f87171' },
  G: { bg: '#16a34a', color: '#fff', border: '#86efac' },
  C: { bg: '#78716c', color: '#fff', border: '#a8a29e' },
}

function parseMana(cost) {
  if (!cost) return []
  const tokens = []
  let i = 0
  while (i < cost.length) {
    if (cost[i] === '{') {
      const end = cost.indexOf('}', i)
      if (end !== -1) { tokens.push(cost.slice(i + 1, end)); i = end + 1; continue }
    }
    i++
  }
  return tokens
}

export default function ManaCost({ cost, size = 18 }) {
  const tokens = parseMana(cost)
  if (!tokens.length) return null

  return (
    <span style={{ display: 'inline-flex', gap: '2px', alignItems: 'center' }}>
      {tokens.map((t, i) => {
        const col = PIP_COLORS[t] || { bg: '#44403c', color: '#d6d3d1', border: '#57534e' }
        return (
          <span key={i} style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: size, height: size, borderRadius: '50%',
            background: col.bg, color: col.color,
            border: `1px solid ${col.border}`,
            fontSize: size * 0.55, fontWeight: '700', lineHeight: 1,
          }}>
            {t}
          </span>
        )
      })}
    </span>
  )
}
