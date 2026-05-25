import { useState, useEffect } from 'react'
import ManaCost from './ManaCost'

const s = {
  wrap: { maxWidth: 680, width: '100%', marginTop: 16 },
  commanderBar: { display: 'flex', alignItems: 'center', gap: 16, background: '#1c1917', border: '1px solid #292524', borderRadius: 12, padding: '12px 20px', marginBottom: 20 },
  cmdImg: { width: 48, height: 48, borderRadius: 6, objectFit: 'cover' },
  cmdName: { fontSize: 15, fontWeight: 700, color: '#f5f5f4' },
  cmdType: { fontSize: 12, color: '#78716c' },
  card: { background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 28 },
  title: { fontSize: 22, fontWeight: 700, color: '#eab308', marginBottom: 6, letterSpacing: '0.05em' },
  sub: { fontSize: 13, color: '#78716c', marginBottom: 20 },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10, marginBottom: 24 },
  psBtn: { padding: '12px 14px', borderRadius: 10, cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s', fontFamily: 'inherit' },
  psLabel: { fontSize: 14, fontWeight: 700, marginBottom: 3 },
  psDesc: { fontSize: 11, lineHeight: 1.4 },
  footer: { display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 4 },
  btnBack: { padding: '10px 22px', background: 'none', border: '1px solid #44403c', borderRadius: 10, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit' },
  btnNext: { padding: '10px 28px', background: 'linear-gradient(180deg,#eab308,#a16207)', border: 'none', borderRadius: 10, color: '#0c0a09', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', fontSize: 15 },
}

export default function StepPlaystyle({ commander, value, onChange, onNext, onBack }) {
  const [playstyles, setPlaystyles] = useState([])

  useEffect(() => {
    fetch('/api/playstyles').then(r => r.json()).then(setPlaystyles).catch(() => {})
  }, [])

  return (
    <div style={s.wrap}>
      {/* Commander pill */}
      <div style={s.commanderBar}>
        {commander.image_url
          ? <img src={commander.image_url} alt={commander.name} style={s.cmdImg} />
          : <div style={{ ...s.cmdImg, background: '#292524', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57534e' }}>?</div>
        }
        <div>
          <div style={s.cmdName}>{commander.name} <ManaCost cost={commander.mana_cost} size={15} /></div>
          <div style={s.cmdType}>{commander.type_line}</div>
        </div>
      </div>

      <div style={s.card}>
        <h2 style={s.title}>Choose a Playstyle</h2>
        <p style={s.sub}>How do you want to win? Auto-detect reads your commander's oracle text.</p>

        <div style={s.grid}>
          {playstyles.map(ps => {
            const selected = value === ps.key
            return (
              <button
                key={ps.key}
                onClick={() => onChange(ps.key)}
                style={{
                  ...s.psBtn,
                  background: selected ? '#422006' : '#0c0a09',
                  border: selected ? '1px solid #ca8a04' : '1px solid #292524',
                  color: selected ? '#fef08a' : '#d6d3d1',
                }}
              >
                <div style={{ ...s.psLabel, color: selected ? '#fde047' : '#f5f5f4' }}>{ps.label}</div>
                <div style={{ ...s.psDesc, color: selected ? '#fef08a' : '#78716c' }}>{ps.description}</div>
              </button>
            )
          })}
        </div>

        <div style={s.footer}>
          <button style={s.btnBack} onClick={onBack}>← Back</button>
          <button style={s.btnNext} onClick={onNext}>
            Continue →
          </button>
        </div>
      </div>
    </div>
  )
}
