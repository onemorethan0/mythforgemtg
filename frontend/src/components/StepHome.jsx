import RecentDecks from './RecentDecks'

// The landing hub: the three things Myth Forge can do, chosen up front so each is
// a first-class entry (Build a deck / Analyze an existing deck / Design one card).
const CHOICES = [
  {
    key: 'build', icon: '🃏', title: 'Build a Deck',
    desc: 'Generate a themed 100-card Commander deck with custom AI art and printable proxies.',
    cta: 'Start building',
  },
  {
    key: 'analyze', icon: '🔍', title: 'Analyze a Deck',
    desc: 'Import a deck you already have to measure its real strength — a simulation-grounded '
      + 'bracket and Power Profile — then retheme it if you like.',
    cta: 'Import & analyze',
  },
  {
    key: 'card', icon: '🂠', title: 'Single Card',
    desc: 'Proxy one real card with new art, or design a custom card from scratch — '
      + 'your own name, cost, rules and flavor.',
    cta: 'Make a card',
  },
  {
    key: 'collection', icon: '🎴', title: 'My Collection',
    desc: 'Browse, add, and edit the cards you own. Powers collection-aware deck building '
      + 'and owned-card upgrade suggestions across the Myth Suite.',
    cta: 'Manage collection',
  },
]

export default function StepHome({ onChoose, onLoadDeck }) {
  return (
    <div style={{ maxWidth: 940, width: '100%', marginTop: 44 }}>
      <div style={{ textAlign: 'center', marginBottom: 34 }}>
        <h1 style={{ fontSize: 30, fontWeight: 700, color: '#eab308', letterSpacing: '0.04em', marginBottom: 10 }}>
          What will you forge?
        </h1>
        <p style={{ fontSize: 14, color: '#78716c', margin: 0 }}>
          Build a deck, measure one you already have, make a single card, or manage your collection.
        </p>
      </div>
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', justifyContent: 'center' }}>
        {CHOICES.map(c => (
          <button
            key={c.key}
            aria-label={c.title}
            onClick={() => onChoose(c.key)}
            style={{
              flex: '1 1 260px', maxWidth: 300, textAlign: 'left', background: '#1c1917',
              border: '1px solid #292524', borderRadius: 16, padding: 24, cursor: 'pointer',
              fontFamily: 'inherit', color: '#f5f5f4', display: 'flex', flexDirection: 'column',
              transition: 'border-color 0.15s, transform 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = '#eab308'; e.currentTarget.style.transform = 'translateY(-2px)' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = '#292524'; e.currentTarget.style.transform = 'none' }}
          >
            <div style={{ fontSize: 34, marginBottom: 12 }}>{c.icon}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#f5f5f4', marginBottom: 8 }}>{c.title}</div>
            <div style={{ fontSize: 13, color: '#a8a29e', lineHeight: 1.55, marginBottom: 16, flex: 1 }}>{c.desc}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#eab308' }}>{c.cta} →</div>
          </button>
        ))}
      </div>
      {onLoadDeck && <RecentDecks onLoad={onLoadDeck} />}
    </div>
  )
}
