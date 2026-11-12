import { useEffect, useState } from 'react'
import RecentDecks from './RecentDecks'
import { readLastDeck, forgetLastDeck, timeAgo } from '../utils/lastDeck'
import { formatRoute } from '../utils/router'

function safeStorage() {
  try { return window.localStorage } catch { return null }
}

// One click back to the deck you last had open. Hidden when there is none, or when it has since been
// deleted (checked with the cheap status call, so a dead link is never offered).
function ContinueBanner() {
  const [last, setLast] = useState(() => readLastDeck(safeStorage()))
  useEffect(() => {
    if (!last) return undefined
    let live = true
    fetch(`/api/deck/${last.id}/status`)
      .then(r => { if (live && r.status === 404) { forgetLastDeck(safeStorage()); setLast(null) } })
      .catch(() => { /* server down: keep offering it; the route reports the failure */ })
    return () => { live = false }
  }, [last])
  if (!last) return null
  return (
    <button
      onClick={() => { window.location.hash = formatRoute('deck', last.id) }}
      style={{
        display: 'flex', alignItems: 'center', gap: 12, width: '100%', maxWidth: 620, margin: '0 auto 26px',
        padding: '12px 18px', borderRadius: 12, cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
        background: 'var(--accent-bg)', border: '1px solid var(--accent-strong)', color: 'var(--accent-text)',
      }}
      title="Open the deck you last had open"
    >
      <span style={{ fontSize: 18 }} aria-hidden="true">↩</span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: 'block', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-muted)' }}>
          Continue where you left off
        </span>
        <span style={{ display: 'block', fontSize: 16, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {last.name}
        </span>
      </span>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{timeAgo(last.at)}</span>
      <span style={{ fontWeight: 700 }}>→</span>
    </button>
  )
}

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
      <ContinueBanner />
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
