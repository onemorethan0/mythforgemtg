import { useEffect, useRef, useState } from 'react'
import AdvisePanel from './AdvisePanel'
import AnimatePanel from './AnimatePanel'
import CardImpactPanel from './CardImpactPanel'
import CardTile from './CardTile'
import { CmcChart, StatBar } from './DeckStatCharts'
import DuelPanel from './DuelPanel'
import MentorChatPanel from './MentorChatPanel'
import ManaCost from './ManaCost'
import MeasurePanel from './MeasurePanel'
import OwnershipBadge from './OwnershipBadge'
import RegenPanel from './RegenPanel'
import SetBible from './SetBible'
import ThreeDPrintPanel from './ThreeDPrintPanel'
import { useGenerate3D } from '../hooks/useGenerate3D'
import { useOwnDeck } from '../hooks/useOwnDeck'
import { notify } from '../utils/toast'
import { searchCards } from '../utils/searchCards'
import { BRACKET_TERMS } from '../glossary'

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

// Display/grouping ORDER — creatures and spells first, lands last. This is purely
// cosmetic (which section/tab appears first) and is independent of the
// CLASSIFICATION precedence below.
const TYPE_ORDER = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Planeswalker', 'Land']

// Classification PRECEDENCE — a card can print more than one of these types on one
// line (an Artifact Creature, a Land Creature like Dryad Arbor, an Artifact Land),
// so only the first matching bucket should win. This mirrors the server's
// authoritative `collection_index.primary_type()` (Land > Creature > Planeswalker >
// Battle > Instant > Sorcery > Enchantment > Artifact) so the two independently
// computed classifications agree. It IS a duplicated reimplementation, though: deck
// cards returned by the build/theme pipeline carry no server-computed primary_type
// field today — that field exists only in collection_index.py, for the separate
// Collection-manager browsing view (`/api/collection`), not for a deck's own cards.
// Ideally this reads a server-provided field once one is threaded through to deck
// cards, instead of re-deriving it here from a substring match on type_line.
const TYPE_PRECEDENCE = ['Land', 'Creature', 'Planeswalker', 'Instant', 'Sorcery', 'Enchantment', 'Artifact']

function groupByType(cards) {
  const groups = {}
  for (const type of TYPE_ORDER) groups[type] = []
  groups['Other'] = []
  for (const c of cards) {
    const tl = c.type_line || ''
    let placed = false
    for (const type of TYPE_PRECEDENCE) {
      if (tl.includes(type)) { groups[type].push(c); placed = true; break }
    }
    if (!placed) groups['Other'].push(c)
  }
  return groups
}

function triggerDownload(url) {
  const a = document.createElement('a'); a.href = url; a.click()
}

// The original-names decklist is produced SERVER-side (/export/decklist). The old
// client version wrote a flat "1 <name>" per entry, which silently dropped every
// duplicate copy — an imported deck whose 30-odd basics aggregate into a handful of
// quantity entries came out as a ~70-card list — and emitted the commander as a
// plain maindeck line, so the file did not re-import as the same deck.

// Themed names beside the real ones. Quantities are the PHYSICAL counts and the
// section headers count physical cards, so an imported deck whose 8 basics live in
// one aggregated entry reads as "Land (8)" and not "Land (1)" — the same
// duplicate-dropping bug the original-names export had. An auto-elected display face
// is a maindeck card, so it is only labelled "Commander:" on a real Commander deck.
function exportThemed(deck) {
  const qty = c => Math.max(1, parseInt(c.quantity, 10) || 1)
  const isCmd = deck.is_commander_deck !== false && !deck.import_auto_face
  const lines = []
  let cards = deck.deck
  if (isCmd) {
    lines.push(`Commander: ${deck.commander.themed_name} (${deck.commander.original_name})`, '')
  } else {
    cards = [deck.commander, ...deck.deck]
  }
  const groups = groupByType(cards)
  for (const type of [...TYPE_ORDER, 'Other']) {
    if (!groups[type]?.length) continue
    lines.push(`// ${type} (${groups[type].reduce((n, c) => n + qty(c), 0)})`)
    groups[type].forEach(c => lines.push(`${qty(c)} ${c.themed_name} (${c.original_name})`))
    lines.push('')
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
  a.download = `${deck.commander.themed_name.replace(/[^a-z0-9]/gi, '_')}_themed.txt`; a.click()
}

// `body` carries optional art overrides (generate_art / art_style / model_speed /
// checkpoint / art_theme). A deck saved straight from an import has none of those
// stored, so this is how its FIRST art run gets requested — see ArtSetupModal.
async function triggerRetheme(jobId, body = {}) {
  const res = await fetch(`/api/deck/${jobId}/retheme`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Retheme failed: ${res.status}`)
  return (await res.json()).job_id
}

// A deck imported and saved to the library carries no theme and no art yet.
function deckHasNoArt(deck) {
  return !!deck && !deck.generate_art
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export default function StepDeck({ deck, jobId, onReset, onRebuild, onRetheme, onDuplicate, onEdit, editingDeck, onDeckChange }) {
  const [filter, setFilter]   = useState('All')
  const [view, setView]       = useState('gallery')
  const [query, setQuery]     = useState('')   // text search across the card list
  // "I own this deck in paper" -> merge its cards into the collection (state +
  // handler live in the hook; the badge/button JSX lives in OwnershipBadge).
  const { ownDeck, addDeckToCollection } = useOwnDeck(deck, jobId, onDeckChange)

  // ── Selection state ───────────────────────────────────────────────────────
  const [selectedKeys, setSelectedKeys]   = useState(new Set())
  const [showRegenPanel, setShowRegenPanel] = useState(false)

  // ── Per-card regen state ──────────────────────────────────────────────────
  const [regenJobId, setRegenJobId]         = useState(null)
  const [regenPending, setRegenPending]     = useState(new Set())   // render_keys in-flight
  const [regenDone, setRegenDone]           = useState(new Set())   // render_keys finished
  const [refreshTs, setRefreshTs]           = useState({})          // render_key → timestamp
  const [regenProgress, setRegenProgress]   = useState(null)        // {current, total, cardName}

  // ── Rebuild-all / retheme / duplicate state ───────────────────────────────
  const [rebuilding, setRebuilding]   = useState(false)
  const [showRebuildModal, setShowRebuildModal] = useState(false)
  const [rebuildArtStyle, setRebuildArtStyle] = useState(deck.art_style || 'mtg_fantasy')
  const [rebuildModelSpeed, setRebuildModelSpeed] = useState(deck.model_speed || 'quality')
  const [rebuildArtStyles, setRebuildArtStyles] = useState([])
  // Pinned style-variant for the rebuild — seeded from the deck's persisted choice.
  const [rebuildVariant, setRebuildVariant] = useState(deck.gen_settings?.style_variant || '')
  const [rethemeing, setRethemeing]   = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [dupMsg, setDupMsg]           = useState(null)   // null | {newJobId, name} | 'error'
  const [deckCheckpoints, setDeckCheckpoints] = useState([])

  // ── Animate (image-to-video) state ────────────────────────────────────────
  const [showAnimatePanel, setShowAnimatePanel] = useState(false)
  const [videoTs, setVideoTs]       = useState({})   // render_key → timestamp (cache-bust)
  const [videoKeys, setVideoKeys]   = useState(() => {
    const s = new Set()
    if (deck?.commander?.has_video) s.add(deck.commander.render_key)
    for (const c of deck?.deck || []) if (c.has_video) s.add(c.render_key)
    return s
  })
  const [videoFmts, setVideoFmts]   = useState(() => {   // render_key → mp4|webp|gif
    const m = {}
    const add = c => { if (c?.has_video) m[c.render_key] = c.video_meta?.format || 'mp4' }
    add(deck?.commander)
    for (const c of deck?.deck || []) add(c)
    return m
  })
  // View preference: show the animated version of cards that have one, or the
  // static still. Persisted across decks; default ON.
  const [showMotion, setShowMotion] = useState(() => {
    try { return localStorage.getItem('mtg_show_motion') !== '0' } catch { return true }
  })
  useEffect(() => {
    try { localStorage.setItem('mtg_show_motion', showMotion ? '1' : '0') } catch {}
  }, [showMotion])
  const [videoHealth, setVideoHealth] = useState(null)   // null | {ok, method, hint, ...}
  const [motionPresets, setMotionPresets] = useState([])
  const [foilStyles, setFoilStyles]       = useState([])
  const [videoFormats, setVideoFormats]   = useState([])
  const [videoLoopStyles, setVideoLoopStyles] = useState([])
  const [videoCaps, setVideoCaps]         = useState(null)   // {motion:{min_s,max_s,default_s}, foil:{...}, fps_options}

  // ── 3D Commander generation (state + fetch/SSE handler live in the hook) ──
  const { state: gen3dState, msg: gen3dMsg, stlUrl: gen3dStlUrl, health: gen3dHealth,
          generate: handleGenerate3D, reset: resetGen3d } = useGenerate3D(jobId)
  const [rebuildCheckpoint, setRebuildCheckpoint] = useState(deck.checkpoint || null)
  // First-art-run setup for a deck that has none yet (a saved import).
  const [showArtSetup, setShowArtSetup] = useState(false)
  const [artSetupTheme, setArtSetupTheme] = useState(deck.theme || '')

  // The `useState(() => ...)` initializers above (rebuildArtStyle/rebuildModelSpeed/
  // rebuildVariant/rebuildCheckpoint/artSetupTheme/videoKeys/videoFmts) only run on
  // this component's FIRST mount. `<StepDeck>` is rendered with no `key` prop, and
  // `handleDuplicate` deliberately keeps the user on this same instance after
  // duplicating a deck ("stay on DECK step — user now views the copy"), so a `deck`/
  // `jobId` prop change with no unmount never re-runs them — stale values from the
  // OLD deck can leak into modals (rebuild/animate/art-setup) that operate on the
  // NEW deck's jobId. Re-seed them explicitly whenever the deck's stable identity
  // (jobId) changes, using React's documented "adjusting state when a prop changes"
  // pattern (a plain comparison during render, not a useEffect): it applies the reset
  // in the SAME render the new jobId arrives in — no stale-value frame — and, unlike
  // an effect, doesn't trip this repo's react-hooks/set-state-in-effect lint rule.
  const [seededJobId, setSeededJobId] = useState(jobId)
  if (jobId !== seededJobId) {
    setSeededJobId(jobId)
    setRebuildArtStyle(deck.art_style || 'mtg_fantasy')
    setRebuildModelSpeed(deck.model_speed || 'quality')
    setRebuildVariant(deck.gen_settings?.style_variant || '')
    setRebuildCheckpoint(deck.checkpoint || null)
    setArtSetupTheme(deck.theme || '')
    setVideoKeys(() => {
      const s = new Set()
      if (deck?.commander?.has_video) s.add(deck.commander.render_key)
      for (const c of deck?.deck || []) if (c.has_video) s.add(c.render_key)
      return s
    })
    setVideoFmts(() => {
      const m = {}
      const add = c => { if (c?.has_video) m[c.render_key] = c.video_meta?.format || 'mp4' }
      add(deck?.commander)
      for (const c of deck?.deck || []) add(c)
      return m
    })
  }

  const evtRef = useRef(null)

  // NOTE: there is deliberately no `if (!deck) return null` here. It used to sit on
  // this line and was doubly wrong: unreachable (the useState calls above already
  // dereference `deck.checkpoint`/`deck.theme`, so a null deck throws before we get
  // here) and harmful (returning early made every hook below it conditional — three
  // rules-of-hooks violations, which crash with "rendered fewer hooks than expected"
  // the moment the early return's branch flips between renders). App.jsx guards the
  // null case at the call site instead, before this component ever mounts.

  // ── Fetch art styles and checkpoints for rebuild modal ─────────────────────
  useEffect(() => {
    fetch('/api/art-styles')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setRebuildArtStyles(d) })
      .catch(() => {})
    fetch('/api/checkpoints')
      .then(r => r.ok ? r.json() : [])
      .then(d => setDeckCheckpoints(Array.isArray(d) ? d : []))
      .catch(() => {})
    fetch('/api/video-health')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setVideoHealth(d) })
      .catch(() => {})
    fetch('/api/video-presets')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.presets) setMotionPresets(d.presets)
        if (d?.foil_styles) setFoilStyles(d.foil_styles)
        if (d?.formats) setVideoFormats(d.formats)
        if (d?.loop_styles) setVideoLoopStyles(d.loop_styles)
        if (d?.caps) setVideoCaps(d.caps)
      })
      .catch(() => {})
  }, [])

  // ── SSE listener for per-card regen job ───────────────────────────────────
  useEffect(() => {
    if (!regenJobId) return
    const src = new EventSource(`/api/deck/${regenJobId}/events`)
    evtRef.current = src

    src.addEventListener('progress', e => {
      try {
        const d = JSON.parse(e.data)
        if ((d.step === 'art' || d.step === 'video') && d.card_num != null) {
          setRegenProgress({ current: d.card_num, total: d.total, cardName: d.card_name,
                             pct: d.pct, kind: d.step })
        }
      } catch {}
    })

    src.addEventListener('card_ready', e => {
      try {
        const d = JSON.parse(e.data)
        setRefreshTs(prev => ({ ...prev, [d.key]: Date.now() }))
        setRegenPending(prev => { const s = new Set(prev); s.delete(d.key); return s })
        setRegenDone(prev => new Set([...prev, d.key]))
        // A regenerated still invalidates its animation (it was made from the old
        // art); the backend deletes the stale clip, so drop the tile's video and
        // show the fresh still until the card is re-animated.
        setVideoKeys(prev => { if (!prev.has(d.key)) return prev; const s = new Set(prev); s.delete(d.key); return s })
        setVideoFmts(prev => { if (!(d.key in prev)) return prev; const m = { ...prev }; delete m[d.key]; return m })
      } catch {}
    })

    // Animate job: a card's MP4 just finished — swap its tile to the looping video.
    src.addEventListener('video_ready', e => {
      try {
        const d = JSON.parse(e.data)
        setVideoKeys(prev => new Set([...prev, d.key]))
        setVideoFmts(prev => ({ ...prev, [d.key]: d.format || 'mp4' }))
        setVideoTs(prev => ({ ...prev, [d.key]: Date.now() }))
        setRegenPending(prev => { const s = new Set(prev); s.delete(d.key); return s })
        setRegenDone(prev => new Set([...prev, d.key]))
      } catch {}
    })

    src.addEventListener('done', () => {
      src.close()
      setRegenJobId(null)
      setRegenPending(new Set())
      setRegenProgress(null)
      setSelectedKeys(new Set())
      setShowRegenPanel(false)
    })

    src.addEventListener('error', e => {
      if (!e.data) return   // connection-level reconnect, not a real error
      src.close()
      setRegenJobId(null)
      setRegenPending(new Set())
      setRegenProgress(null)
      // Always tell the user. This used to be `try { alert(JSON.parse(...).msg) } catch {}`,
      // so a malformed error payload was swallowed entirely — and since the three setters
      // above have already cleared the spinner, a silently-failed regen looked exactly like
      // a successful one. Fall back to the raw payload rather than showing nothing.
      let msg
      try { msg = JSON.parse(e.data).msg || '' } catch { msg = String(e.data || '').slice(0, 300) }
      notify('error', `Regen failed: ${msg || 'the server reported an error but sent no detail.'}`)
    })

    src.onerror = () => {
      fetch(`/api/deck/${regenJobId}/status`).then(r => r.json()).then(d => {
        if (d.status === 'done' || d.status === 'error') {
          src.close(); setRegenJobId(null); setRegenPending(new Set()); setRegenProgress(null)
        }
      }).catch(() => {})
    }

    return () => src.close()
  }, [regenJobId])

  // ── Selection helpers ─────────────────────────────────────────────────────
  // Shift-click selects the RANGE between the last clicked card and this one (in the
  // order currently displayed), so picking "all the creatures" on a 100-card deck is
  // one gesture instead of thirty clicks. Plain click toggles a single card.
  const lastClickedKey = useRef(null)

  function toggleSelect(key, shiftKey = false) {
    // Read the anchor HERE, not inside the updater: setState updaters run later, by
    // which point lastClickedKey.current has already been reassigned to `key` below —
    // so the range check would always compare a key against itself and never fire.
    const anchor = lastClickedKey.current
    setSelectedKeys(prev => {
      const s = new Set(prev)
      if (shiftKey && anchor && anchor !== key) {
        const order = visibleCards.map(c => c.render_key)
        const a = order.indexOf(anchor), b = order.indexOf(key)
        if (a !== -1 && b !== -1) {
          for (const k of order.slice(Math.min(a, b), Math.max(a, b) + 1)) s.add(k)
          return s
        }
      }
      s.has(key) ? s.delete(key) : s.add(key)
      return s
    })
    lastClickedKey.current = key
  }
  function clearSelection() { setSelectedKeys(new Set()); lastClickedKey.current = null }

  // ── Regen handlers ────────────────────────────────────────────────────────
  async function handleStartRegen(payload) {
    setShowRegenPanel(false)
    setRegenPending(new Set(payload.cards.map(c => c.render_key)))
    try {
      const res = await fetch(`/api/deck/${jobId}/regen-cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRegenJobId(data.job_id)
    } catch (err) {
      setRegenPending(new Set())
      notify('error', `Could not start regen: ${err.message}`)
    }
  }

  async function handleStartAnimate(payload) {
    setShowAnimatePanel(false)
    setRegenPending(new Set(payload.cards.map(c => c.render_key)))
    try {
      const res = await fetch(`/api/deck/${jobId}/animate-cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRegenJobId(data.job_id)   // reuse the SSE listener (progress + video_ready + done)
    } catch (err) {
      setRegenPending(new Set())
      notify('error', `Could not start animation: ${err.message}`)
    }
  }

  async function handleRebuildAll() {
    // Show the rebuild options modal
    setShowRebuildModal(true)
  }

  async function handleConfirmRebuild() {
    if (rebuilding) return
    setRebuilding(true)
    setShowRebuildModal(false)
    // Only send the pinned variant if it actually belongs to the chosen style.
    const _rbStyle = rebuildArtStyles.find(s => s.key === rebuildArtStyle)
    const _rbVariant = (_rbStyle?.variants || []).some(v => v.label === rebuildVariant)
      ? rebuildVariant : ''
    try {
      const res = await fetch(`/api/deck/${jobId}/rebuild`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          art_style:   rebuildArtStyle,
          model_speed: rebuildModelSpeed,
          checkpoint:  rebuildCheckpoint || null,
          face_key:    deck.face_key || null,
          face_gender: deck.face_gender || 'either',
          crew_key:    deck.crew_key || null,
          crew_gender: deck.crew_gender || 'either',
          // Preserve the deck's advanced settings and apply the chosen flavor.
          // '' = Variety mix (per-card rotation).
          gen_settings: { ...(deck.gen_settings || {}), style_variant: _rbVariant },
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      onRebuild(data.job_id)
    } catch (err) {
      notify('error', `Could not start rebuild: ${err.message}`)
      setRebuilding(false)
    }
  }

  async function handleRethemeAll() {
    if (rethemeing) return
    // A deck with no art yet (saved straight from an import) has no theme and no
    // art style stored, so firing a bare retheme would rename the cards and stop.
    // Ask for those once, up front, instead.
    if (deckHasNoArt(deck)) { setShowArtSetup(true); return }
    setRethemeing(true)
    try {
      const newJobId = await triggerRetheme(jobId)
      if (onRetheme) onRetheme(newJobId)
      else if (onRebuild) onRebuild(newJobId)  // fallback: treat like rebuild nav
    } catch (err) {
      notify('error', `Could not start retheme: ${err.message}`)
      setRethemeing(false)
    }
  }

  // First art run for an un-arted deck: theme + style come from the modal, and
  // generate_art:true is what actually unlocks the art phase in _run_retheme.
  async function handleConfirmArtSetup() {
    if (rethemeing) return
    setRethemeing(true)
    setShowArtSetup(false)
    try {
      const newJobId = await triggerRetheme(jobId, {
        art_theme:    artSetupTheme.trim() || null,
        generate_art: true,
        art_style:    rebuildArtStyle,
        model_speed:  rebuildModelSpeed,
        checkpoint:   rebuildCheckpoint || null,
      })
      if (onRetheme) onRetheme(newJobId)
      else if (onRebuild) onRebuild(newJobId)
    } catch (err) {
      notify('error', `Could not start art generation: ${err.message}`)
      setRethemeing(false)
    }
  }

  async function handleDuplicate() {
    if (duplicating) return
    setDuplicating(true)
    setDupMsg(null)
    try {
      const res = await fetch(`/api/deck/${jobId}/duplicate`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDupMsg({ newJobId: data.new_job_id, name: data.themed_name })
      if (onDuplicate) onDuplicate(data.new_job_id)
    } catch {
      setDupMsg('error')
    } finally {
      setDuplicating(false)
    }
  }

  // ── Derived data ──────────────────────────────────────────────────────────
  const groups      = groupByType(deck.deck)
  const types       = ['All', ...TYPE_ORDER.filter(t => groups[t]?.length > 0)]
  if (groups['Other']?.length) types.push('Other')
  const visibleCards = searchCards(filter === 'All' ? deck.deck : (groups[filter] || []), query)

  const allCardsFlat    = [deck.commander, ...deck.deck]
  const selectedCardData = allCardsFlat.filter(c => selectedKeys.has(c.render_key))

  const { commander, stats } = deck
  // Single custom-card mode: the deck is "of one", so deck-level chrome (stats,
  // type filters, the empty deck grid) is hidden and labels are re-pointed.
  const single = deck?.mode === 'single_card'

  function regenStatusFor(key) {
    if (regenPending.has(key)) return 'pending'
    if (regenDone.has(key))    return 'done'
    return 'idle'
  }

  const btnBase = { padding: '5px 14px', borderRadius: 8, fontFamily: 'inherit', fontSize: 12, cursor: 'pointer', border: '1px solid #44403c' }
  // Labelled action clusters (Download / Regenerate / Deck) so related controls read
  // as a set instead of one undifferentiated row of buttons.
  const actGroupLabel = { fontSize: 9.5, color: '#57534e', textTransform: 'uppercase',
                          letterSpacing: '0.1em', fontWeight: 700, marginBottom: 5 }
  const actGroupRow   = { display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }

  return (
    <div style={{ width: '100%', maxWidth: 1200, marginTop: 24, paddingBottom: selectedKeys.size > 0 || regenProgress ? 80 : 0 }}>

      {/* Commander banner */}
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 24, marginBottom: 24, alignItems: 'flex-start' }}>
        {/* Commander image — clickable for selection */}
        <div
          style={{ position: 'relative', flexShrink: 0, cursor: 'pointer' }}
          onClick={() => toggleSelect(commander.render_key)}
          title="Click to select commander for regen"
        >
          {(() => {
            const imgStyle = { width: single ? 300 : 180, borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.6)', outline: selectedKeys.has(commander.render_key) ? '3px solid #eab308' : 'none', display: 'block' }
            const stillSrc = (commander.has_render || refreshTs[commander.render_key])
              ? `/api/deck/${jobId}/card-image/${commander.render_key}${refreshTs[commander.render_key] ? `?t=${refreshTs[commander.render_key]}` : ''}`
              : commander.scryfall_img || null
            // Show the animation when the commander has one (mp4 → <video>, webp/gif → <img>),
            // unless the viewer turned animations off.
            if (showMotion && videoKeys.has(commander.render_key)) {
              const vts  = videoTs[commander.render_key] || 0
              const vfmt = videoFmts[commander.render_key] || commander.video_meta?.format || 'mp4'
              const vsrc = `/api/deck/${jobId}/card-video/${commander.render_key}${vts ? `?t=${vts}` : ''}`
              return (vfmt === 'webp' || vfmt === 'gif')
                ? <img src={vsrc} alt={commander.themed_name} style={imgStyle} />
                : <video src={vsrc} poster={stillSrc || undefined} autoPlay loop muted playsInline preload="auto"
                    style={{ ...imgStyle, background: '#000' }} />
            }
            return stillSrc
              ? <img src={stillSrc} alt={commander.themed_name} style={imgStyle} />
              : <div style={{ width: single ? 300 : 180, height: single ? 420 : 252, background: '#0c0a09', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57534e' }}>No art</div>
          })()}
          {/* Status overlays for commander */}
          {regenPending.has(commander.render_key) && (
            <div style={{ position: 'absolute', inset: 0, borderRadius: 12, background: 'rgba(0,0,0,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 22, animation: 'spin-slow 1.5s linear infinite' }}>⚙️</div>
              <div style={{ fontSize: 9, color: '#eab308', fontWeight: 700 }}>Generating…</div>
            </div>
          )}
          {selectedKeys.has(commander.render_key) && !regenPending.has(commander.render_key) && (
            <div style={{ position: 'absolute', top: 6, right: 6, width: 22, height: 22, borderRadius: '50%', background: '#eab308', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 900, color: '#0c0a09' }}>✓</div>
          )}
          {regenDone.has(commander.render_key) && !regenPending.has(commander.render_key) && (
            <div style={{ position: 'absolute', top: 6, left: 6, fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 700, background: '#14532d', color: '#86efac', border: '1px solid #166534' }}>NEW</div>
          )}
          <div style={{ position: 'absolute', bottom: 6, left: '50%', transform: 'translateX(-50%)', fontSize: 9, color: '#78716c', whiteSpace: 'nowrap', background: 'rgba(0,0,0,0.6)', padding: '2px 6px', borderRadius: 4 }}>
            {single ? 'click to re-roll art' : 'click to select'}
          </div>
        </div>

        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <div style={{ fontSize: 11, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 6 }}>{single ? 'Custom Card' : 'Commander'}</div>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: '#fde047', margin: '0 0 4px', lineHeight: 1.2, overflowWrap: 'anywhere' }}>{commander.themed_name}</h1>
          {commander.themed_name !== commander.original_name && (
            <div style={{ fontSize: 13, color: '#57534e', marginBottom: 10 }}>({commander.original_name})</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <ManaCost cost={commander.mana_cost} size={20} />
          </div>
          <div style={{ fontSize: 13, color: '#a8a29e', marginBottom: 6 }}>{commander.type_line}</div>
          <div style={{ fontSize: 12, color: '#d6d3d1', lineHeight: 1.6, marginBottom: 16, maxWidth: 440 }}>{commander.oracle_text}</div>
          {commander.flavor_text && (
            <div style={{ fontSize: 12, color: '#78716c', fontStyle: 'italic', marginBottom: 16, maxWidth: 440 }}>{commander.flavor_text}</div>
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {!single && <span style={{ fontSize: 12, padding: '4px 12px', background: '#422006', border: '1px solid #ca8a04', borderRadius: 20, color: '#fde047' }}>{deck.playstyle}</span>}
            {!single && deck.bracket && (
              <span
                title={`Built to target: ${(BRACKET_TERMS[deck.bracket] || {}).desc || deck.bracket_label}`}
                style={{ fontSize: 12, padding: '4px 12px', borderRadius: 20, fontWeight: 700, cursor: 'help',
                background: ['','#052e16','#1a2e05','#422006','#431407','#450a0a'][deck.bracket] || '#1c1917',
                border: `1px solid ${['','#4ade80','#a3e635','#eab308','#f97316','#ef4444'][deck.bracket] || '#44403c'}`,
                color: ['','#4ade80','#a3e635','#eab308','#f97316','#ef4444'][deck.bracket] || '#a8a29e',
              }}>
                B{deck.bracket} {deck.bracket_label}
              </span>
            )}
            <OwnershipBadge deck={deck} single={single} ownDeck={ownDeck} onAdd={addDeckToCollection} />
            {deck.theme && <span style={{ fontSize: 12, padding: '4px 12px', background: '#0c0a09', border: '1px solid #292524', borderRadius: 20, color: '#a8a29e' }}>{deck.theme}</span>}
            {!single && <span style={{ fontSize: 12, padding: '4px 12px', background: '#0c0a09', border: '1px solid #292524', borderRadius: 20, color: '#a8a29e' }}>{stats?.total_cards || deck.deck.length + 1} cards</span>}
            {!single && deck.collection && deck.collection.enabled && (
              <span title={`From your Myth Suite collection (${deck.collection.collection_size} owned cards)`}
                    style={{ fontSize: 12, padding: '4px 12px', background: '#052e16',
                             border: '1px solid #16a34a', borderRadius: 20, color: '#4ade80' }}>
                🎴 {deck.collection.owned}/{deck.collection.total} from your collection
                {deck.collection.source === 'collection' && ' · owned only'}
              </span>
            )}
          </div>

          {/* Playstyle strategy summary */}
          {deck.playstyle_description && (
            <div style={{ fontSize: 12.5, color: '#a8a29e', lineHeight: 1.55, marginTop: 12, maxWidth: 460 }}>
              <span style={{ color: '#fde047', fontWeight: 700 }}>Strategy: </span>{deck.playstyle_description}
            </div>
          )}
          {/* Deck composition one-liner. compute_stats(card, []) yields empty
              type_counts and avg 0, so a single card printed a bare "· avg MV 0.0". */}
          {!single && stats?.type_counts && (
            <div style={{ fontSize: 11.5, color: '#78716c', marginTop: 8, maxWidth: 460 }}>
              {['Creature','Instant','Sorcery','Artifact','Enchantment','Planeswalker','Land']
                .filter(t => stats.type_counts[t])
                .map(t => `${stats.type_counts[t]} ${t.toLowerCase()}${stats.type_counts[t] > 1 ? (t === 'Sorcery' ? ' sorceries' : 's') : ''}`)
                .join(' · ')}
              {stats.average_cmc != null && ` · avg MV ${stats.average_cmc.toFixed(1)}`}
            </div>
          )}

          <ThreeDPrintPanel
            single={single}
            hasRender={commander.has_render}
            state={gen3dState}
            msg={gen3dMsg}
            stlUrl={gen3dStlUrl}
            health={gen3dHealth}
            onGenerate={handleGenerate3D}
            onReset={resetGen3d}
          />
        </div>

        {/* Stats panel */}
        {!single && stats && (
          <div style={{ width: 200, flexShrink: 0 }}>
            <div style={{ fontSize: 12, color: '#78716c', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Deck Stats</div>
            <div style={{ fontSize: 13, color: '#a8a29e', marginBottom: 4 }}>Avg CMC: <span style={{ color: '#fde047', fontWeight: 700 }}>{(stats.average_cmc ?? stats.avg_cmc)?.toFixed?.(2) ?? '—'}</span></div>
            <div style={{ height: 1, background: '#292524', margin: '10px 0' }} />
            {stats.type_counts && Object.entries(stats.type_counts).map(([type, count]) => (
              <StatBar key={type} label={type} value={count} max={30} color='#ca8a04' />
            ))}
            {stats.cmc_curve && <div style={{ marginTop: 12 }}><CmcChart curve={stats.cmc_curve} /></div>}
            <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
            <div style={{ fontSize: 12, color: '#a8a29e' }}>Lands: <span style={{ color: '#86efac' }}>{stats.land_count}</span></div>

            {/* Deck health — curve vs the reference curve for this commander's mana
                value, and whether the manabase can actually cast the deck. Advisory:
                deck_quality measures the built list, it never changes it. */}
            {/* Strict collection builds report what the collection could not cover.
                Gated on deck.collection ALONE — nesting this inside the quality block
                meant an empty quality measurement silently suppressed the reporting.
                Without it the honesty stops at the SSE stream, which is long gone by
                the time anyone reads the finished deck. */}
            {deck?.collection?.shortfall && Object.keys(deck.collection.shortfall).length > 0 && (
              <>
                <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
                <div style={{ fontSize: 11, color: '#fbbf24' }}>
                  Collection couldn’t cover:{' '}
                  {Object.entries(deck.collection.shortfall)
                    .map(([k, v]) => `${k.replace(/_/g, ' ')} (${v})`).join(', ')}
                </div>
              </>
            )}

            {stats.quality && (
              <>
                <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
                <div style={{ fontSize: 11, color: '#78716c', marginBottom: 6 }}>Deck health</div>
                {stats.quality.curve && (
                  <div style={{ fontSize: 12, marginBottom: 8 }}>
                    <span style={{ color: '#a8a29e' }}>Curve: </span>
                    <span style={{ fontWeight: 700, color:
                      stats.quality.curve.verdict === 'ok' ? '#86efac' : '#fbbf24' }}>
                      {stats.quality.curve.verdict}
                    </span>
                    <span style={{ color: '#78716c' }}> · avg {stats.quality.curve.average}</span>
                  </div>
                )}
                {/* Mana-value histogram: `buckets`/`target` (per-MV counts, 7 = "7 or more")
                    have always been in the API response, just never drawn — the panel only
                    ever showed the top-line verdict + average. A bare "top-heavy" verdict
                    doesn't say WHERE; this does, at a glance. The white tick is the reference
                    curve for this commander's own mana value (deck_quality.curve_target),
                    not a fixed ideal — a 7-drop commander's target already skews cheaper. */}
                {stats.quality.curve?.buckets && stats.quality.curve?.target && (() => {
                  const curve = stats.quality.curve
                  const mvs = [1, 2, 3, 4, 5, 6, 7]
                  const val = (obj, mv) => obj[mv] ?? obj[String(mv)] ?? 0
                  const maxVal = Math.max(1, ...mvs.map((mv) => Math.max(val(curve.buckets, mv), val(curve.target, mv))))
                  const H = 46
                  return (
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 5, height: H + 32, marginBottom: 8 }}>
                      {mvs.map((mv) => {
                        const actual = val(curve.buckets, mv)
                        const target = val(curve.target, mv)
                        const barH = Math.max(actual > 0 ? 2 : 0, Math.round((actual / maxVal) * H))
                        const tickY = H - Math.round((target / maxVal) * H)
                        const over = actual > target
                        const under = actual < target
                        return (
                          <div key={mv} title={`MV ${mv === 7 ? '7+' : mv}: ${actual} card${actual === 1 ? '' : 's'} (target ${target})`}
                               style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, cursor: 'help' }}>
                            <div style={{ position: 'relative', width: '100%', height: H, display: 'flex', alignItems: 'flex-end' }}>
                              <div style={{
                                width: '100%', height: barH, borderRadius: '3px 3px 0 0',
                                background: over ? '#fbbf24' : under ? '#57534e' : '#38bdf8',
                              }} />
                              {target > 0 && (
                                <div style={{ position: 'absolute', left: -1, right: -1, top: tickY, height: 2, background: '#f5f5f4', opacity: 0.85 }} />
                              )}
                            </div>
                            <div style={{ fontSize: 9.5, color: '#78716c', marginTop: 3 }}>{mv === 7 ? '7+' : mv}</div>
                            <div style={{ fontSize: 9, fontWeight: 600, color: over ? '#fbbf24' : under ? '#a8a29e' : '#86efac' }}>{actual}</div>
                          </div>
                        )
                      })}
                    </div>
                  )
                })()}
                {stats.quality.colors && (
                  <div style={{ fontSize: 12, marginBottom: 6 }}>
                    <span style={{ color: '#a8a29e' }}>Mana: </span>
                    <span style={{ fontWeight: 700, color: stats.quality.colors.ok ? '#86efac' : '#f87171' }}>
                      {stats.quality.colors.ok ? 'castable' : 'short on sources'}
                    </span>
                    {!stats.quality.colors.ok && Object.entries(stats.quality.colors.short || {}).map(([c, n]) => (
                      <div key={c} style={{ fontSize: 11, color: '#f87171', marginTop: 2 }}>
                        {c}: {stats.quality.colors.sources?.[c] ?? 0} sources, wants {stats.quality.colors.required?.[c]}
                      </div>
                    ))}
                  </div>
                )}
                {/* Whether there is enough mana at all — the "Mana:" row above only asks
                    whether it is the right COLOURS, so a deck with far too few lands passed
                    it without comment. "ramp-dependent" is deliberately NOT styled as a
                    fault: measured over the corpus, 10.9% of real decks run under 33 lands
                    and 68% of those are carried by ramp, so it describes how the deck plays
                    rather than accusing it of being broken. */}
                {stats.quality.mana && (
                  <div style={{ fontSize: 12, marginBottom: 6 }}>
                    <span style={{ color: '#a8a29e' }}>Mana sources: </span>
                    <span style={{
                      fontWeight: 700,
                      color: stats.quality.mana.verdict === 'short' ? '#f87171'
                           : stats.quality.mana.verdict === 'ramp-dependent' ? '#fbbf24'
                           : '#86efac',
                    }}>
                      {stats.quality.mana.sources}
                    </span>
                    <span style={{ color: '#78716c' }}>
                      {' '}({stats.quality.mana.lands} lands + {stats.quality.mana.ramp} ramp)
                    </span>
                    {(stats.quality.mana.notes || []).map((n, i) => (
                      <div key={i} style={{
                        fontSize: 11, marginTop: 2,
                        color: stats.quality.mana.verdict === 'short' ? '#f87171' : '#78716c',
                      }}>{n}</div>
                    ))}
                  </div>
                )}
                {(stats.quality.curve?.notes || []).slice(0, 2).map((n, i) => (
                  <div key={i} style={{ fontSize: 11, color: '#78716c', marginTop: 2 }}>{n}</div>
                ))}
              </>
            )}
            {/* Off-meta read — how far this list sits from the typical deck under this
                commander (EDHREC lift). A DIFFERENT axis from bracket/strength: a precon
                and a wild brew can rate the same bracket. Advisory; lift_stats measures
                the built list and never changes it.
                Coverage is shown ALWAYS, not just when low: an EDHREC page lists ~250
                cards, so a chunk of every deck is simply unmeasured, and a percentage
                presented without its sample size is a confident fabrication. */}
            {stats.offmeta && stats.offmeta.measured > 0 && (() => {
              const om = stats.offmeta;
              const VERDICTS = {
                // Each verdict describes its QUADRANT, and every quadrant is cut at a
                // population median — so the wording has to stay comparative. Median
                // staples_pct per bucket, over the 238 corpus decks with a cached page:
                // on-rails 98.4 · focused-with-spice 88.2 · off-plan 82.2 · brew 77.0.
                // Nothing here may claim a deck lacks synergy: the LOWEST bucket still has
                // three quarters of its measured cards on positive lift.
                'on-rails':           ['Stock list',    '#fbbf24', "plays this commander's most-played cards, and little else"],
                'focused-with-spice': ['Focused brew',  '#86efac', 'on-theme, with cards outside the usual list'],
                // Was "using the commander as a backbone for something else" — which says the
                // deck is NOT built around its commander, while a median 77.0% of its measured
                // cards are ones this commander wants. The defining feature of this quadrant is
                // the SPREAD, not an absence of synergy.
                'brew':               ['Off-beat brew', '#c4b5fd', 'on-theme overall, but a wide gulf between its best and loosest picks'],
                // NOT "unfocused": this is the residual quadrant of a 2x2 split at POPULATION
                // medians, so it means "less commander-leaning than most decks", not "few
                // synergy cards". Measured over 238 corpus decks, 80% of the decks landing here
                // are still ABOVE their commander's page median with a median 82% of measured
                // cards on positive lift — the old blurb told a quarter of all decks something
                // demonstrably false about themselves. See the note in lift_stats.py.
                'off-plan':           ['Relaxed build', '#a8a29e', 'evenly on-theme, leaning on the commander less than most decks do'],
                'insufficient-data':  ['Not enough data', '#78716c', 'too little of this deck appears on EDHREC to judge'],
              };
              const [label, color, blurb] = VERDICTS[om.verdict] || ['—', '#a8a29e', ''];
              return (
                <>
                  <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
                  <div style={{ fontSize: 11, color: '#78716c', marginBottom: 6 }}>Off-meta read</div>
                  <div style={{ fontSize: 12, marginBottom: 4 }}>
                    <span style={{ fontWeight: 700, color }}>{label}</span>
                    <span style={{ color: '#78716c' }}> · {blurb}</span>
                  </div>
                  {om.verdict !== 'insufficient-data' && (
                    <div style={{ fontSize: 11, color: '#a8a29e', marginTop: 4 }}>
                      Synergy {om.synergy > 0 ? '+' : ''}{om.synergy}
                      <span style={{ color: '#78716c' }}> (typical here {om.baseline > 0 ? '+' : ''}{om.baseline})</span>
                      {' · '}spread {om.synergy_range}
                      {' · '}{om.staples_pct}% on-theme
                    </div>
                  )}
                  {/* Coverage carries a CONFIDENCE band, not just a percentage. Corpus
                      coverage runs p10 0.22 to p90 0.98, so a bare "45%" invites the reader to
                      weigh a thin reading the same as a near-complete one. Bands are the corpus
                      median/p25 on coverage AND on the absolute measured count — 40% of a
                      40-card list is a smaller sample than 40% of a 99-card one. */}
                  <div style={{ fontSize: 11, color: '#78716c', marginTop: 2 }}>
                    Measured {om.measured} of {om.total} cards ({Math.round(om.coverage * 100)}%)
                    {om.confidence && (
                      <span style={{
                        marginLeft: 6, padding: '1px 6px', borderRadius: 3, fontSize: 10,
                        border: '1px solid currentColor',
                        color: om.confidence === 'high' ? '#86efac'
                             : om.confidence === 'medium' ? '#eab308' : '#f87171',
                      }}>
                        {om.confidence} confidence
                      </span>
                    )}
                    {om.verdict === 'insufficient-data' && ' — showing raw numbers only'}
                  </div>
                  {om.confidence === 'low' && om.verdict !== 'insufficient-data' && (
                    <div style={{ fontSize: 11, color: '#78716c', marginTop: 2, fontStyle: 'italic' }}>
                      Most of this deck isn't on the commander's EDHREC page, so read the verdict
                      as a hint rather than a measurement.
                    </div>
                  )}
                </>
              );
            })()}
            {/* Archetypes — what the DECK plays, vs what the commander's text claims.
                Worth showing side by side because they routinely disagree: a commander
                can declare a theme the deck barely supports (and a companion declares
                none at all while its deck plainly has three). deck_themes is a local
                text scan, so this costs nothing and is always available. */}
            {stats.archetypes?.merged?.length > 0 && (() => {
              const a = stats.archetypes;
              const pretty = (t) => t.replace(/^tribal_/, '').replace(/_/g, ' ');
              const dropped = (a.commander || []).filter((t) => !a.merged.includes(t));
              return (
                <>
                  <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
                  <div style={{ fontSize: 11, color: '#78716c', marginBottom: 6 }}>Archetypes</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 4 }}>
                    {a.merged.map((t) => (
                      <span key={t} style={{
                        fontSize: 11, padding: '2px 8px', borderRadius: 12,
                        background: '#1c1917', color: '#a8a29e',
                        border: `1px solid ${(a.deck || []).includes(t) ? '#44403c' : '#292524'}`,
                      }}>{pretty(t)}</span>
                    ))}
                  </div>
                  {dropped.length > 0 && (
                    <div style={{ fontSize: 11, color: '#78716c', marginTop: 2 }}>
                      {dropped.map(pretty).join(', ')} — named by the commander, but the
                      deck barely plays {dropped.length > 1 ? 'them' : 'it'}
                    </div>
                  )}
                </>
              );
            })()}
            {/* Color identity (mana pip counts) */}
            {stats.color_pips && Object.keys(stats.color_pips).length > 0 && (
              <>
                <div style={{ height: 1, background: '#292524', margin: '12px 0' }} />
                <div style={{ fontSize: 11, color: '#78716c', marginBottom: 6 }}>Color pips</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {Object.entries(stats.color_pips).map(([c, n]) => (
                    <span key={c} style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11,
                      padding: '2px 8px', borderRadius: 12,
                      background: { W:'#3a3526', U:'#0c2748', B:'#2b2735', R:'#3a1414', G:'#11331c', C:'#1c1917' }[c] || '#1c1917',
                      color:      { W:'#f5e6c8', U:'#7dd3fc', B:'#c4b5fd', R:'#fca5a5', G:'#86efac', C:'#a8a29e' }[c] || '#a8a29e',
                    }}>{c} {n}</span>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Where this deck came from. Retheme/rebuild/duplicate each leave the source
          intact and write a NEW deck — this is the only place that says so. */}
      {(deck.rethemed_from || deck.rebuilt_from || deck.copied_from) && (
        <div style={{ marginBottom: 12, fontSize: 12, color: '#78716c', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span>
            {deck.rethemed_from ? '✏️ Re-themed from' : deck.rebuilt_from ? '🎲 Re-rolled art from' : '📋 Copied from'} an earlier deck
          </span>
          <span style={{ color: '#44403c' }}>— that one is untouched and still in History.</span>
        </div>
      )}

      {/* The world these cards are printed in. Generated and persisted by every
          themed build (build/rebuild/retheme and single-card all write world_bible),
          but until now only ever rendered in the Theme step's pre-build preview. */}
      <SetBible bible={deck.world_bible} theme={deck.theme} />

      {/* Imported-deck provenance. Where the list came from, whether the "commander"
          is a real one or an auto-elected display face, and — the part that used to
          be invisible after the build — which source cards never resolved and are
          therefore NOT in this deck. */}
      {!single && deck.imported && (
        <div style={{
          marginBottom: 20, padding: '10px 14px', borderRadius: 10,
          background: '#0c1a2e', border: '1px solid #1e40af',
          fontSize: 12, color: '#93c5fd', display: 'flex', flexWrap: 'wrap',
          gap: 10, alignItems: 'center',
        }}>
          <span style={{ fontWeight: 700 }}>📥 Imported deck</span>
          {deck.import_name && <span style={{ color: '#bfdbfe' }}>“{deck.import_name}”</span>}
          {deck.import_source && (
            <span style={{ color: '#60a5fa', textTransform: 'capitalize' }}>via {deck.import_source}</span>
          )}
          <span style={{ color: '#64748b' }}>
            {(deck.deck || []).reduce((n, c) => n + (c.quantity || 1), 0) + 1} cards
          </span>
          {deckHasNoArt(deck) && (
            <span style={{ color: '#c4b5fd' }}>· original card art (no AI art yet)</span>
          )}
          {deck.import_auto_face && (
            <span style={{ color: '#fcd34d' }}>
              · no commander zone — “{deck.commander?.original_name}” is the display face
            </span>
          )}
          {(deck.import_unresolved || []).length > 0 && (
            <span style={{
              color: '#fca5a5', width: '100%', marginTop: 2, lineHeight: 1.5,
            }} title={(deck.import_unresolved || []).join('\n')}>
              ⚠ {deck.import_unresolved.length} card(s) from the source could not be matched
              on Scryfall and are <strong>not</strong> in this deck:{' '}
              {deck.import_unresolved.slice(0, 10).join(', ')}
              {deck.import_unresolved.length > 10 ? ` … +${deck.import_unresolved.length - 10} more` : ''}
            </span>
          )}
        </div>
      )}

      {/* Simulation-grounded strength + upgrade advisor (Myth Suite C3/C4) — full decks only */}
      {!single && (
        <div style={{ marginBottom: 20 }}>
          {/* keyed on swap_count so an applied swap resets the cached measurement
              (the old profile no longer matches the modified list) */}
          <MeasurePanel key={`${jobId}-${deck.swap_count || 0}`} jobId={jobId} cached={deck.last_measure} />
          <AdvisePanel key={`adv-${jobId}`} jobId={jobId} onApplied={onDeckChange} />
          {/* Ask about ONE named card. Keyed on swap_count like MeasurePanel:
              an applied swap changes the list, so a cached verdict is stale. */}
          <CardImpactPanel key={`imp-${jobId}-${deck.swap_count || 0}`} jobId={jobId} />
          {/* Keyed on swap_count too, like the panels above: a duel result or mentor
              conversation grounded in the pre-swap decklist must not linger on screen
              looking current after the user applies a swap. */}
          <DuelPanel key={`duel-${jobId}-${deck.swap_count || 0}`} jobId={jobId} />
          <MentorChatPanel key={`mentor-${jobId}-${deck.swap_count || 0}`} jobId={jobId} />
        </div>
      )}

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Type filter */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: 1 }}>
          {!single && types.map(t => (
            <button key={t} onClick={() => setFilter(t)} style={{
              fontSize: 12, padding: '5px 14px', borderRadius: 20, border: 'none', cursor: 'pointer', fontFamily: 'inherit',
              background: filter === t ? '#ca8a04' : '#1c1917',
              color: filter === t ? '#0c0a09' : '#a8a29e',
              fontWeight: filter === t ? 700 : 400,
            }}>
              {t} {t !== 'All' && groups[t] ? `(${groups[t].length})` : t === 'All' ? `(${deck.deck.length})` : ''}
            </button>
          ))}
        </div>

        {/* Text search */}
        {!single && (
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="🔎 Search cards…"
              aria-label="Search cards"
              style={{
                padding: '6px 28px 6px 12px', borderRadius: 8, border: '1px solid #292524',
                background: '#1c1917', color: '#f5f5f4', fontSize: 12, fontFamily: 'inherit',
                width: 180, outline: 'none',
              }}
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                aria-label="Clear search"
                style={{
                  position: 'absolute', right: 6, background: 'none', border: 'none',
                  color: '#78716c', cursor: 'pointer', fontSize: 12, padding: 2, fontFamily: 'inherit',
                }}
              >
                ✕
              </button>
            )}
          </div>
        )}

        {/* View toggle */}
        {!single && <div style={{ display: 'flex', gap: 4 }}>
          {['gallery', 'list'].map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              padding: '5px 14px', borderRadius: 8, border: '1px solid #292524', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12,
              background: view === v ? '#292524' : 'transparent', color: view === v ? '#f5f5f4' : '#57534e',
            }}>
              {v === 'gallery' ? '⊞ Gallery' : '☰ List'}
            </button>
          ))}
        </div>}

        {/* Actions, grouped by INTENT. Previously one flat row of ten buttons mixed
            downloads, a view toggle and three different regeneration actions whose
            names didn't say what they did ("Rebuild All" only re-rolled art while
            "Retheme" regenerated everything). Each group is labelled, and every
            regenerate button now states its scope. */}
        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-start' }}>

          {/* — Download — */}
          <div>
            <div style={actGroupLabel}>Download</div>
            <div style={actGroupRow}>
              {single && (
                <a href={`/api/deck/${jobId}/card-image/${commander.render_key}`}
                   download={`${(commander.themed_name || 'card').replace(/[^a-z0-9]+/gi, '_')}.png`}
                   title="The finished card as a PNG"
                   style={{ ...btnBase, background: '#14532d', color: '#86efac',
                            border: '1px solid #15803d', fontWeight: 600, textDecoration: 'none' }}>↓ Card PNG</a>
              )}
              <button onClick={() => triggerDownload(`/api/deck/${jobId}/export/pdf`)} title={single ? 'Print-ready PDF — a sheet of this card, ready to cut' : 'Print-ready PDF of every card, 9 per page'}
                style={{ ...btnBase, background: '#14532d', color: '#86efac', border: '1px solid #15803d', fontWeight: 600 }}>↓ Print PDF</button>
              <button onClick={() => triggerDownload(`/api/deck/${jobId}/export/zip`)} title="ZIP of the individual card images"
                style={{ ...btnBase, background: '#1e3a5f', color: '#93c5fd', border: '1px solid #1d4ed8', fontWeight: 600 }}>↓ Images</button>
              {videoKeys.size > 0 && (
                <button onClick={() => triggerDownload(`/api/deck/${jobId}/export/videos`)} title="ZIP of the animated cards"
                  style={{ ...btnBase, background: '#0c2a4d', color: '#7dd3fc', border: '1px solid #0ea5e9', fontWeight: 600 }}>↓ Animations ({videoKeys.size})</button>
              )}
              {!single && (
                <button onClick={() => triggerDownload(`/api/deck/${jobId}/export/decklist`)}
                  title="Decklist of the ORIGINAL card names with real quantities — paste into Moxfield/Archidekt, or back into Import to verify the deck is unchanged"
                  style={{ ...btnBase, background: 'none', color: '#a8a29e' }}>Decklist</button>
              )}
              {!single && (
                <button onClick={() => exportThemed(deck)} title="Decklist showing the themed names next to the real ones"
                  style={{ ...btnBase, background: 'none', color: '#a8a29e' }}>Themed list</button>
              )}
            </div>
          </div>

          {/* — Regenerate: smallest scope first, each says what it changes — */}
          <div>
            <div style={actGroupLabel}>Regenerate</div>
            <div style={actGroupRow}>
              {onRebuild && (
                <button onClick={handleRebuildAll} disabled={rebuilding || rethemeing}
                  title={single
                    ? 'Re-roll the art from the same art prompt. Everything printed on the card stays as it is.'
                    : 'Re-roll the ART on every card using the existing names and prompts. Names, rules text and flavor stay exactly as they are.'}
                  style={{ ...btnBase, background: rebuilding ? '#2e1065' : '#3b0764', color: rebuilding ? '#7c3aed' : '#c4b5fd', border: '1px solid #7c3aed', fontWeight: 600, opacity: rebuilding ? 0.7 : 1 }}>
                  {rebuilding ? '⏳ Starting…' : '🎲 New art only'}
                </button>
              )}
              <button
                onClick={handleRethemeAll}
                disabled={rethemeing || rebuilding}
                title={deckHasNoArt(deck)
                  ? (single
                      ? 'This card has no AI art yet. Pick a theme and art style and generate art for it. Saves as a new card; this one is kept.'
                      : 'This deck has no AI art yet. Pick a theme and art style, and generate custom art for every card on this exact list. Saves as a new deck; this one is kept.')
                  : single
                    ? 'Write a fresh art prompt for this card and generate new art from it. Your name, rules text and flavor are kept exactly as you wrote them. Saves as a new card; this one is kept.'
                    : 'Re-run the FULL generation on the same cards: new themed names, flavor text AND new art (same theme + settings). Saves as a new deck; this one is kept.'}
                style={{ ...btnBase,
                  background: rethemeing ? '#1e1b4b' : (deckHasNoArt(deck) ? '#3b0764' : '#1e3a5f'),
                  color: rethemeing ? '#818cf8' : (deckHasNoArt(deck) ? '#c4b5fd' : '#93c5fd'),
                  border: `1px solid ${rethemeing ? '#4f46e5' : (deckHasNoArt(deck) ? '#7c3aed' : '#1d4ed8')}`,
                  fontWeight: 600, opacity: rethemeing ? 0.7 : 1 }}
              >
                {rethemeing ? '⏳ Starting…'
                  : deckHasNoArt(deck) ? '🎨 Generate AI art…'
                  : single ? '✏️ New art direction' : '✏️ New names + art'}
              </button>
              {onEdit && (
                <button
                  onClick={() => onEdit(deck)}
                  disabled={rebuilding || rethemeing || duplicating || !!editingDeck}
                  title={single
                    ? 'Re-open the card designer with every field of this card pre-filled so you can change it. Generating saves a new card — this one is kept.'
                    : "Re-open the builder with this deck's commander, theme, art style and every setting pre-filled so you can change them. Building saves a new deck — this one is kept."}
                  style={{ ...btnBase, background: '#1c1408', color: '#fde047', border: '1px solid #ca8a04', fontWeight: 600, opacity: editingDeck ? 0.7 : 1 }}
                >
                  {editingDeck ? '⏳ Opening…' : single ? '✎ Edit this card…' : '🎛️ Change settings…'}
                </button>
              )}
            </div>
          </div>

          {/* — This deck — */}
          <div>
            <div style={actGroupLabel}>{single ? 'Card' : 'Deck'}</div>
            <div style={actGroupRow}>
              {videoKeys.size > 0 && (
                <button
                  onClick={() => setShowMotion(m => !m)}
                  title={showMotion ? 'Showing animated cards — click to show the static art instead'
                                    : 'Showing static art — click to play the animated versions'}
                  style={{ ...btnBase, background: showMotion ? '#0c2a4d' : 'none',
                    color: showMotion ? '#7dd3fc' : '#78716c',
                    border: `1px solid ${showMotion ? '#0ea5e9' : '#44403c'}`, fontWeight: 600 }}
                >{showMotion ? '▶ Motion: On' : '❚❚ Motion: Off'}</button>
              )}
              <button
                onClick={handleDuplicate}
                disabled={duplicating || rebuilding || rethemeing}
                title={single ? 'Create an independent copy of this card — the original is preserved unchanged'
                             : 'Create an independent copy of this deck — the original is preserved unchanged'}
                style={{ ...btnBase, background: duplicating ? '#1c2030' : '#0f172a', color: duplicating ? '#64748b' : '#7dd3fc', border: '1px solid #1e40af', fontWeight: 600, opacity: duplicating ? 0.7 : 1 }}
              >
                {duplicating ? '⏳ Copying…' : '📋 Duplicate'}
              </button>
              {/* Only single-card mode short-circuits back into its own designer;
                  a deck still returns to the home hub, as it always has. */}
              <button onClick={() => onReset(single ? 'card' : undefined)}
                title={single ? 'Design another card from scratch' : 'Start a brand-new deck from scratch'}
                style={{ ...btnBase, background: 'linear-gradient(180deg,#eab308,#a16207)', color: '#0c0a09', border: 'none', fontWeight: 700 }}>
                {single ? '🂠 New Card' : 'New Deck'}</button>
            </div>
          </div>
        </div>
        {/* Duplicate feedback banner */}
        {dupMsg && dupMsg !== 'error' && (
          <div style={{ marginTop: 8, padding: '8px 14px', background: '#0c1a2e', border: '1px solid #1e40af', borderRadius: 8, fontSize: 12, color: '#7dd3fc', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📋</span>
            <span>Copy created: <strong>{dupMsg.name || dupMsg.newJobId}</strong> — find it in History.</span>
          </div>
        )}
        {dupMsg === 'error' && (
          <div style={{ marginTop: 8, padding: '8px 14px', background: '#1c0a0a', border: '1px solid #7f1d1d', borderRadius: 8, fontSize: 12, color: '#fca5a5' }}>
            ⚠ Duplicate failed. Check that the deck has finished building.
          </div>
        )}
      </div>

      {/* Selection hint */}
      {/* Discoverability: per-card regen/animate is only reachable by clicking a card,
          and this hint used to be #44403c (near-invisible on the dark background) and
          didn't mention animation — so the whole feature set read as missing. */}
      {selectedKeys.size === 0 && !regenProgress && view === 'gallery' && (
        <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 12, textAlign: 'center',
                      padding: '7px 12px', borderRadius: 8, background: '#1c191788',
                      border: '1px dashed #44403c' }}>
          {single ? (
            <>👆 <b style={{ color: '#fde047' }}>Click your card above</b> to re-roll its art or animate it.</>
          ) : (
            <>👆 <b style={{ color: '#fde047' }}>Click any card</b> to select it — then regenerate its
              art or add animation. Shift-click or “Select visible” for several at once.</>
          )}
        </div>
      )}

      {/* Search with no hits */}
      {query.trim() && visibleCards.length === 0 && view === 'gallery' && (
        <div style={{ textAlign: 'center', color: '#57534e', fontSize: 13, padding: '30px 0' }}>
          No cards match “{query.trim()}”
        </div>
      )}

      {/* Card gallery — a deck of one has its only card in the hero banner */}
      {view === 'gallery' && !single && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
          {visibleCards.map((card) => (
            <CardTile
              // render_key is the deck's own stable, unique-per-card identifier
              // (already used everywhere else in this file to key per-card state:
              // selectedKeys/regenPending/regenDone/videoKeys/...) — unlike
              // original_name+index, it doesn't shift when a swap changes the
              // list's order, so React can't misattribute a tile's local hover/
              // video-failure state to the wrong card during the transition.
              key={card.render_key}
              card={card}
              jobId={jobId}
              selected={selectedKeys.has(card.render_key)}
              onSelect={!regenProgress ? toggleSelect : null}
              regenStatus={regenStatusFor(card.render_key)}
              refreshTs={refreshTs[card.render_key] || 0}
              hasVideo={videoKeys.has(card.render_key)}
              showMotion={showMotion}
              videoTs={videoTs[card.render_key] || 0}
              videoFmt={videoFmts[card.render_key]}
            />
          ))}
        </div>
      )}

      {/* List view */}
      {view === 'list' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {(filter === 'All' ? TYPE_ORDER.concat('Other') : [filter]).map(type => {
            const cards = searchCards(groups[type] || [], query)
            if (!cards?.length) return null
            return (
              <div key={type} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '6px 0', borderBottom: '1px solid #1c1917', marginBottom: 6 }}>
                  {type} ({cards.length})
                </div>
                {cards.map((c, i) => (
                  <div key={i}
                    onClick={(e) => !regenProgress && toggleSelect(c.render_key, e.shiftKey)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 12, padding: '7px 8px', borderRadius: 6,
                      background: selectedKeys.has(c.render_key) ? '#1c1408' : i % 2 === 0 ? '#0c0a09' : 'transparent',
                      cursor: 'pointer',
                      outline: selectedKeys.has(c.render_key) ? '1px solid #ca8a04' : 'none',
                    }}
                  >
                    <div style={{ width: 16, height: 16, borderRadius: '50%', flexShrink: 0,
                      background: selectedKeys.has(c.render_key) ? '#eab308' : '#1c1917',
                      border: `1px solid ${selectedKeys.has(c.render_key) ? '#eab308' : '#44403c'}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 900, color: '#0c0a09',
                    }}>{selectedKeys.has(c.render_key) ? '✓' : ''}</div>
                    <ManaCost cost={c.mana_cost} size={16} />
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: '#f5f5f4' }}>{c.themed_name}</span>
                    {c.themed_name !== c.original_name && <span style={{ fontSize: 11, color: '#57534e' }}>({c.original_name})</span>}
                    <span style={{ fontSize: 11, color: '#44403c', minWidth: 100, textAlign: 'right' }}>{c.type_line?.replace('Legendary ', '').replace(' — ', ' ')}</span>
                    {c.power && <span style={{ fontSize: 11, color: '#78716c', minWidth: 30, textAlign: 'right' }}>{c.power}/{c.toughness}</span>}
                    {regenStatusFor(c.render_key) === 'pending' && <span style={{ fontSize: 10, color: '#eab308' }}>⚙️</span>}
                    {regenStatusFor(c.render_key) === 'done'    && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: '#14532d', color: '#86efac', fontWeight: 700 }}>NEW</span>}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}

      {/* ── Fixed bottom bar: selection actions ── */}
      {selectedKeys.size > 0 && !regenProgress && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 100,
          background: '#1c1917', borderTop: '1px solid #44403c',
          padding: '12px 24px', display: 'flex', alignItems: 'center', gap: 14,
          boxShadow: '0 -4px 24px rgba(0,0,0,0.5)',
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: '#fde047' }}>
            {selectedKeys.size} card{selectedKeys.size !== 1 ? 's' : ''} selected
          </span>
          <div style={{ flex: 1 }} />
          {!single && (
            <button
              onClick={() => setSelectedKeys(new Set(visibleCards.map(c => c.render_key)))}
              style={{ ...btnBase, background: 'none', color: '#78716c', fontSize: 11 }}
            >Select visible</button>
          )}
          <button
            onClick={clearSelection}
            style={{ ...btnBase, background: 'none', color: '#78716c', fontSize: 11 }}
          >✕ Clear</button>
          <button
            onClick={() => setShowAnimatePanel(true)}
            title={videoHealth?.ok ? 'Animate the selected cards (art motion and/or foil sheen)'
                                   : 'Add a foil/holo sheen (a video model is needed for art motion)'}
            style={{ ...btnBase,
              background: '#0c2a4d', color: '#7dd3fc', border: '1px solid #0ea5e9',
              fontWeight: 700, fontSize: 13, padding: '8px 18px', cursor: 'pointer' }}
          >
            ✨ Animate {selectedKeys.size}
          </button>
          <button
            onClick={() => setShowRegenPanel(true)}
            style={{ ...btnBase, background: '#3b0764', color: '#c4b5fd', border: '1px solid #7c3aed', fontWeight: 700, fontSize: 13, padding: '8px 20px' }}
          >
            🎲 Regenerate {selectedKeys.size} Card{selectedKeys.size !== 1 ? 's' : ''}
          </button>
        </div>
      )}

      {/* ── Fixed bottom bar: regen progress ── */}
      {regenProgress && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 100,
          background: '#1c1917', borderTop: '1px solid #44403c',
          padding: '10px 24px', display: 'flex', flexDirection: 'column', gap: 6,
          boxShadow: '0 -4px 24px rgba(0,0,0,0.5)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ fontSize: 13, animation: 'spin-slow 1.5s linear infinite' }}>⚙️</div>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#eab308' }}>
              {regenProgress.kind === 'video' ? 'Animating cards…' : 'Regenerating cards…'} {regenProgress.current}/{regenProgress.total}
            </span>
            {regenProgress.cardName && (
              <span style={{ fontSize: 12, color: '#78716c', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {regenProgress.cardName}
              </span>
            )}
            <span style={{ fontSize: 12, color: '#57534e' }}>{(regenProgress.pct || 0).toFixed(0)}%</span>
          </div>
          <div style={{ height: 4, background: '#292524', borderRadius: 2 }}>
            <div style={{ height: 4, background: '#7c3aed', borderRadius: 2, width: `${regenProgress.pct || 0}%`, transition: 'width 0.4s ease' }} />
          </div>
        </div>
      )}

      {/* ── Regen panel modal ── */}
      {showRegenPanel && (
        <RegenPanel
          selectedCards={selectedCardData}
          onStart={handleStartRegen}
          onClose={() => setShowRegenPanel(false)}
          defaultArtStyle={deck.art_style || 'mtg_fantasy'}
          defaultModelSpeed={deck.model_speed || 'quality'}
          defaultCheckpoint={deck.checkpoint || null}
          commanderOriginalName={deck.commander?.original_name}
          savedFaceKey={deck.face_key || null}
          savedFaceGender={deck.face_gender || 'either'}
          savedCrewKey={deck.crew_key || null}
          savedCrewGender={deck.crew_gender || 'either'}
          single={single}
        />
      )}

      {/* ── Animate panel modal ── */}
      {showAnimatePanel && (
        <AnimatePanel
          selectedCards={selectedCardData}
          presets={motionPresets}
          foilStyles={foilStyles}
          formats={videoFormats}
          loopStyles={videoLoopStyles}
          caps={videoCaps}
          health={videoHealth}
          onStart={handleStartAnimate}
          onClose={() => setShowAnimatePanel(false)}
        />
      )}

      {/* ── Rebuild modal ── */}
      {/* First art run for a deck that has none — a decklist imported and saved to
          the library. Without this the only art control lived in the build wizard,
          which a saved import never passes through. */}
      {showArtSetup && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 200, padding: 16,
        }}
          onClick={e => { if (e.target === e.currentTarget) setShowArtSetup(false) }}
        >
          <div style={{
            background: '#1c1917', border: '1px solid #44403c', borderRadius: 16,
            width: '100%', maxWidth: 440, boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
            padding: 24, display: 'flex', flexDirection: 'column', gap: 16,
          }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, color: '#c4b5fd', fontWeight: 700 }}>🎨 Generate AI art</h3>
              <div style={{ fontSize: 12, color: '#78716c', marginTop: 4, lineHeight: 1.5 }}>
                Themed names, flavor text and custom art for <strong>every card on this
                exact list</strong> — no cards are added, removed or substituted. Saves as
                a new deck; this one is kept as the original.
              </div>
            </div>

            <div>
              <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Theme
              </label>
              <textarea
                value={artSetupTheme}
                onChange={e => setArtSetupTheme(e.target.value)}
                rows={3}
                placeholder="e.g. sunken art-deco city ruled by clockwork whales"
                style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 12, fontFamily: 'inherit', boxSizing: 'border-box', resize: 'vertical' }}
              />
              <div style={{ fontSize: 11, color: '#57534e', marginTop: 4 }}>
                Leave blank to theme around the deck's face card.
              </div>
            </div>

            <div>
              <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Art Style
              </label>
              <select
                value={rebuildArtStyle}
                onChange={e => setRebuildArtStyle(e.target.value)}
                style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 11, fontFamily: 'inherit', boxSizing: 'border-box' }}
              >
                {rebuildArtStyles.length > 0 ? (
                  rebuildArtStyles.map(s => (
                    <option key={s.key} value={s.key} disabled={!s.ready && !s.partial}>
                      {s.icon} {s.label}{s.ready ? '' : s.partial ? ' (partial)' : ' (missing)'}
                    </option>
                  ))
                ) : (
                  <option value="mtg_fantasy">MTG Fantasy</option>
                )}
              </select>
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button onClick={() => setShowArtSetup(false)}
                style={{ ...btnBase, background: 'none', color: '#a8a29e', border: '1px solid #44403c' }}>Cancel</button>
              <button onClick={handleConfirmArtSetup}
                style={{ ...btnBase, background: '#3b0764', color: '#c4b5fd', border: '1px solid #7c3aed', fontWeight: 700 }}>
                Generate art
              </button>
            </div>
          </div>
        </div>
      )}

      {showRebuildModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 200, padding: 16,
        }}
          onClick={e => { if (e.target === e.currentTarget) setShowRebuildModal(false) }}
        >
          <div style={{
            background: '#1c1917', border: '1px solid #44403c', borderRadius: 16,
            width: '100%', maxWidth: 400, boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
            padding: 24, display: 'flex', flexDirection: 'column', gap: 16,
          }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, color: '#fde047', fontWeight: 700 }}>{single ? '🎲 New art for this card' : '🔄 Rebuild Deck'}</h3>
              <div style={{ fontSize: 12, color: '#78716c', marginTop: 4 }}>
                Generate new card art with different settings
              </div>
            </div>

            <div>
              <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Art Style
              </label>
              <select
                value={rebuildArtStyle}
                onChange={e => setRebuildArtStyle(e.target.value)}
                style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 11, fontFamily: 'inherit', boxSizing: 'border-box' }}
              >
                {rebuildArtStyles.length > 0 ? (
                  rebuildArtStyles.map(s => (
                    <option key={s.key} value={s.key} disabled={!s.ready && !s.partial}>
                      {s.icon} {s.label}{s.ready ? '' : s.partial ? ' (partial)' : ' (missing)'}
                    </option>
                  ))
                ) : (
                  <option value="mtg_fantasy">MTG Fantasy</option>
                )}
              </select>
            </div>

            {/* Style-variant selector — only when the chosen style exposes flavors */}
            {(() => {
              const st = rebuildArtStyles.find(s => s.key === rebuildArtStyle)
              const variants = (st && Array.isArray(st.variants)) ? st.variants : []
              if (variants.length === 0) return null
              return (
                <div>
                  <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    {st.label} Flavor
                  </label>
                  <select
                    value={variants.some(v => v.label === rebuildVariant) ? rebuildVariant : ''}
                    onChange={e => setRebuildVariant(e.target.value)}
                    style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 11, fontFamily: 'inherit', boxSizing: 'border-box' }}
                  >
                    <option value="">✨ Variety mix (each card varies)</option>
                    {variants.map(v => (
                      <option key={v.label} value={v.label} disabled={!v.ready}>
                        {v.ready ? '✓' : '⚠'} {v.label}{v.ready ? '' : ' (LoRA missing)'}
                      </option>
                    ))}
                  </select>
                </div>
              )
            })()}

            <div>
              <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Image Model
              </label>
              {deckCheckpoints.length > 0 ? (() => {
                const activeCkpt   = deckCheckpoints.find(c => c.filename === rebuildCheckpoint)
                const activeType   = (activeCkpt?.type || '').toUpperCase()
                const isSchnellAct = rebuildCheckpoint?.toLowerCase().includes('schnell')
                const isDevAct     = activeType.includes('FLUX') && !isSchnellAct
                const isSDXLAct    = activeType.includes('SDXL')
                const isSd35Act    = activeType.includes('SD') && !isSDXLAct && !activeType.includes('FLUX')
                const hasDev_   = deckCheckpoints.some(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))
                const hasSch_   = deckCheckpoints.some(c => c.filename.toLowerCase().includes('schnell'))
                const hasSDXL_  = deckCheckpoints.some(c => (c.type||'').toUpperCase().includes('SDXL'))
                const hasSd35_  = deckCheckpoints.some(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') && !t.includes('FLUX') })
                const pickRebuild = (fn, speed) => { setRebuildCheckpoint(fn || null); if (speed) setRebuildModelSpeed(speed) }
                const btnSt = { padding: '8px 12px', borderRadius: 8, fontSize: 11, fontFamily: 'inherit', cursor: 'pointer', border: '1px solid #292524', flex: 1, textAlign: 'left' }
                return (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {hasDev_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))?.filename, 'quality')}
                        style={{ ...btnSt, background: isDevAct ? '#1c1410' : '#0c0a09', color: isDevAct ? '#eab308' : '#a8a29e', borderColor: isDevAct ? '#ca8a04' : '#292524', fontWeight: isDevAct ? 700 : 400 }}>
                        <div>✦ Quality</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>FLUX Dev</div>
                      </button>
                    )}
                    {hasSDXL_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => (c.type||'').toUpperCase().includes('SDXL'))?.filename, null)}
                        style={{ ...btnSt, background: isSDXLAct ? '#120a1e' : '#0c0a09', color: isSDXLAct ? '#a78bfa' : '#a8a29e', borderColor: isSDXLAct ? '#a78bfa' : '#292524', fontWeight: isSDXLAct ? 700 : 400 }}>
                        <div>🎨 Illustrious XL</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>SDXL</div>
                      </button>
                    )}
                    {hasSd35_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') && !t.includes('FLUX') })?.filename, 'sd35')}
                        style={{ ...btnSt, background: isSd35Act ? '#100a18' : '#0c0a09', color: isSd35Act ? '#818cf8' : '#a8a29e', borderColor: isSd35Act ? '#818cf8' : '#292524', fontWeight: isSd35Act ? 700 : 400 }}>
                        <div>✧ SD 3.5</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>SD 3.5 Large</div>
                      </button>
                    )}
                    {hasSch_ && (
                      <button onClick={() => pickRebuild(deckCheckpoints.find(c => c.filename.toLowerCase().includes('schnell'))?.filename, 'fast')}
                        style={{ ...btnSt, background: isSchnellAct ? '#0a1008' : '#0c0a09', color: isSchnellAct ? '#4ade80' : '#a8a29e', borderColor: isSchnellAct ? '#4ade80' : '#292524', fontWeight: isSchnellAct ? 700 : 400 }}>
                        <div>⚡ Fast</div><div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>FLUX Schnell</div>
                      </button>
                    )}
                  </div>
                )
              })() : (
                <select value={rebuildModelSpeed} onChange={e => setRebuildModelSpeed(e.target.value)}
                  style={{ width: '100%', background: '#0c0a09', color: '#f5f5f4', border: '1px solid #44403c', borderRadius: 6, padding: '8px 10px', fontSize: 11, fontFamily: 'inherit', boxSizing: 'border-box' }}>
                  <option value="quality">Quality (FLUX dev)</option>
                  <option value="fast">Fast (FLUX schnell)</option>
                </select>
              )}
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
              <button onClick={() => setShowRebuildModal(false)} style={{ padding: '6px 16px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer', fontWeight: 600, border: '1px solid #44403c', background: '#292524', color: '#a8a29e' }}>
                Cancel
              </button>
              <button onClick={handleConfirmRebuild} disabled={rebuilding} style={{ padding: '6px 16px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer', fontWeight: 600, border: '1px solid #7c3aed', background: '#3b0764', color: '#c4b5fd', opacity: rebuilding ? 0.7 : 1 }}>
                {rebuilding ? '⏳ Starting…' : '🔄 Rebuild'}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin-slow {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
