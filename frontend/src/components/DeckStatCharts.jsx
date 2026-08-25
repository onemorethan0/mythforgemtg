export function StatBar({ label, value, max, color }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: '#a8a29e' }}>{label}</span>
        <span style={{ fontSize: 12, color: '#f5f5f4', fontWeight: 700 }}>{value}</span>
      </div>
      <div style={{ height: 4, background: '#292524', borderRadius: 2 }}>
        <div style={{ height: 4, background: color, borderRadius: 2, width: `${Math.min(100, (value / max) * 100)}%`, transition: 'width 0.5s' }} />
      </div>
    </div>
  )
}

export function CmcChart({ curve }) {
  if (!curve) return null
  const entries = Object.entries(curve).sort((a, b) => Number(a[0]) - Number(b[0]))
  const maxVal = Math.max(...entries.map(([, v]) => v), 1)
  return (
    <div>
      <div style={{ fontSize: 12, color: '#78716c', marginBottom: 8 }}>Mana Curve</div>
      <div style={{ display: 'flex', gap: 4, alignItems: 'flex-end', height: 60 }}>
        {entries.map(([cmc, count]) => (
          <div key={cmc} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
            <div style={{ width: '100%', background: '#ca8a04', borderRadius: '3px 3px 0 0', height: `${(count / maxVal) * 52}px`, minHeight: count > 0 ? 4 : 0 }} />
            <span style={{ fontSize: 10, color: '#78716c' }}>{cmc === '7' ? '7+' : cmc}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
