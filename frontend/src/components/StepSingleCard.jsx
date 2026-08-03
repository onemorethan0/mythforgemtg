import { useEffect, useMemo, useRef, useState } from 'react'
import ManaCost from './ManaCost'
import AdvancedPanel from './AdvancedPanel'
import { toGenSettingsPayload } from '../config/genSettings'

// Structured "vision" chip options — mirror StepTheme so a single card themes
// with the same world-bible pipeline as a deck.
const VISION_GENRES = ['High Fantasy', 'Dark Fantasy', 'Sci-Fi', 'Cyberpunk', 'Post-Apocalyptic',
                       'Mythic / Legend', 'Steampunk', 'Gothic', 'Historical', 'Cosmic Horror']
const VISION_MOODS  = ['Grim', 'Heroic', 'Whimsical', 'Eerie', 'Serene', 'Epic',
                       'Gritty', 'Mysterious', 'Romantic', 'Ominous']
const VISION_LIGHTING = ['Warm / golden', 'Cold / neon', 'Muted', 'Vibrant', 'High-contrast',
                         'Pastel', 'Moody / dark', 'Ethereal glow']
const RARITIES = [
  { key: 'common',   label: 'Common',   dot: '#3f3f46' },
  { key: 'uncommon', label: 'Uncommon', dot: '#9ca3af' },
  { key: 'rare',     label: 'Rare',     dot: '#d4af37' },
  { key: 'mythic',   label: 'Mythic',   dot: '#d97706' },
  { key: 'special',  label: 'Special',  dot: '#a855f7' },
]
const WUBRG = ['W', 'U', 'B', 'R', 'G']
const MANA_EXAMPLES = ['{2}{W}{U}', '{1}{B}{B}', '{3}{R}', '{G}{G}', '{X}{U}{R}', '{4}']
const TYPE_EXAMPLES = ['Legendary Creature — Human Knight', 'Instant', 'Sorcery',
                       'Artifact — Equipment', 'Enchantment — Aura', 'Legendary Planeswalker — Hero',
                       'Land', 'Creature — Dragon']
// Mirrors SingleCardModel's Field(max_length=…) in server.py — the browser should
// stop the user at the same place the API would reject them.
const LIMITS = { name: 160, mana_cost: 80, type_line: 160, oracle_text: 2000, flavor_text: 600 }

const SPEEDS = [
  { key: 'quality', label: 'Quality',  note: 'FLUX dev · best detail' },
  { key: 'turbo',   label: 'Turbo',    note: '8-step · ~4× faster' },
  { key: 'fast',    label: 'Fast',     note: 'FLUX schnell' },
  { key: 'sd35',    label: 'SD 3.5',   note: 'SD 3.5 Large' },
  { key: 'krea',    label: 'Krea',     note: 'FLUX.1 Krea dev' },
  { key: 'qwen',    label: 'Qwen',     note: 'Qwen-Image (no LoRAs)' },
]

// Flatten the structured vision into one art-theme brief (same shape as App.composeVision).
function composeVision(setting, moods, genres, lighting, inspiration) {
  const p = []
  if (setting && setting.trim()) p.push(setting.trim())
  if (genres && genres.length)   p.push('Genre: ' + genres.join(', '))
  if (moods && moods.length)     p.push('Mood: ' + moods.join(', '))
  if (lighting && lighting.length) p.push('Overall lighting and atmosphere: ' + lighting.join(', '))
  if (inspiration && inspiration.trim()) p.push('Inspired by ' + inspiration.trim())
  return p.join('. ')
}

// A cost typed without braces ("2WU") is unambiguous, so show the user what it
// will become rather than silently producing a colourless, pip-less card. Mirrors
// server._normalize_mana_cost — keep the two in step.
const SHORTHAND_MANA = /\d+|[WUBRGCXYZS]/gi
export function normalizeManaCost(raw) {
  const s = (raw || '').trim()
  if (!s || s.includes('{')) return s
  const compact = s.replace(/[\s/]/g, '')
  if (!compact) return s
  const parts = compact.match(SHORTHAND_MANA) || []
  if (parts.join('') !== compact) return s
  return parts.map(p => `{${p.toUpperCase()}}`).join('')
}

// Colour identity implied by a mana cost, so the preview frame matches what the
// backend will derive when the user hasn't pinned colours by hand.
export function colorsFromCost(cost) {
  const out = []
  for (const m of (normalizeManaCost(cost).match(/\{([^}]+)\}/g) || [])) {
    for (const L of WUBRG) if (m.toUpperCase().includes(L) && !out.includes(L)) out.push(L)
  }
  return WUBRG.filter(c => out.includes(c))
}

const s = {
  wrap: { maxWidth: 980, width: '100%', marginTop: 16 },
  card: { background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 28 },
  title: { fontSize: 22, fontWeight: 700, color: '#eab308', marginBottom: 6, letterSpacing: '0.05em' },
  sub: { fontSize: 13, color: '#78716c', marginBottom: 20 },
  groupHead: { display: 'flex', alignItems: 'center', gap: 10, margin: '26px 0 16px' },
  groupNum: { flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: '#ca8a04', color: '#0c0a09', fontSize: 12, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' },
  groupTitle: { fontSize: 14, fontWeight: 700, color: '#eab308', letterSpacing: '0.04em', textTransform: 'uppercase', whiteSpace: 'nowrap' },
  groupSub: { fontSize: 11.5, color: '#57534e', whiteSpace: 'nowrap' },
  groupRule: { flex: 1, height: 1, background: '#292524' },
  label: { fontSize: 13, color: '#a8a29e', marginBottom: 8, display: 'block' },
  input: { width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10, padding: '10px 14px', color: '#f5f5f4', fontSize: 14, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' },
  inputBad: { borderColor: '#b91c1c' },
  textarea: { width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10, padding: '12px 16px', color: '#f5f5f4', fontSize: 14, outline: 'none', resize: 'vertical', fontFamily: 'inherit', minHeight: 70, boxSizing: 'border-box' },
  row: { display: 'flex', gap: 14, marginBottom: 16, flexWrap: 'wrap' },
  field: { flex: 1, minWidth: 160 },
  chip: (on) => ({ fontSize: 12, padding: '5px 12px', borderRadius: 20, cursor: 'pointer', fontFamily: 'inherit',
                   background: on ? '#ca8a04' : '#0c0a09', color: on ? '#0c0a09' : '#a8a29e',
                   border: `1px solid ${on ? '#ca8a04' : '#44403c'}`, fontWeight: on ? 700 : 400 }),
  chipGrid: { display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 },
  exGrid: { display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0 14px' },
  exBtn: { fontSize: 11, padding: '4px 10px', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 16, color: '#78716c', cursor: 'pointer', fontFamily: 'inherit' },
  seg: (on) => ({ flex: 1, padding: '9px 10px', textAlign: 'center', cursor: 'pointer', fontSize: 13, fontFamily: 'inherit',
                  background: on ? '#ca8a04' : '#0c0a09', color: on ? '#0c0a09' : '#a8a29e', fontWeight: on ? 700 : 400,
                  border: '1px solid #44403c' }),
  segWrap: { display: 'flex', borderRadius: 10, overflow: 'hidden', marginBottom: 8 },
  artRow: { display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px', background: '#0c0a09', border: '1px solid #292524', borderRadius: 10, marginBottom: 16 },
  toggle: (on) => ({ width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer', position: 'relative', flexShrink: 0, background: on ? '#16a34a' : '#44403c' }),
  toggleThumb: (on) => ({ position: 'absolute', top: 2, left: on ? 18 : 2, width: 16, height: 16, background: '#fff', borderRadius: '50%', transition: 'left 0.2s' }),
  hint: { fontSize: 11.5, color: '#57534e', marginTop: -8, marginBottom: 16, lineHeight: 1.5 },
  warn: { fontSize: 12, color: '#fbbf24', marginTop: 6, lineHeight: 1.5 },
  err:  { fontSize: 12, color: '#f87171', marginTop: 6, lineHeight: 1.5 },
  footer: { display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 28, alignItems: 'center' },
  btnBack: { padding: '10px 22px', background: 'none', border: '1px solid #44403c', borderRadius: 10, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit' },
  btnNext: { padding: '10px 28px', background: 'linear-gradient(180deg,#eab308,#a16207)', border: 'none', borderRadius: 10, color: '#0c0a09', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', fontSize: 15 },
  btnDisabled: { opacity: 0.4, cursor: 'not-allowed' },
}

function Group({ num, title, sub, children }) {
  return (
    <>
      <div style={s.groupHead}>
        <span style={s.groupNum}>{num}</span>
        <span style={s.groupTitle}>{title}</span>
        {sub && <span style={s.groupSub}>{sub}</span>}
        <span style={s.groupRule} />
      </div>
      {children}
    </>
  )
}

function Chips({ options, value, onChange }) {
  const toggle = (o) => onChange(value.includes(o) ? value.filter(x => x !== o) : [...value, o])
  return (
    <div style={s.chipGrid}>
      {options.map(o => (
        <button key={o} type="button" style={s.chip(value.includes(o))} onClick={() => toggle(o)}>{o}</button>
      ))}
    </div>
  )
}

function Toggle({ on, onChange, title, note, noteColor }) {
  return (
    <div style={s.artRow}>
      <button type="button" style={s.toggle(on)} onClick={() => onChange(!on)} aria-pressed={on} aria-label={title}>
        <span style={s.toggleThumb(on)} />
      </button>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, color: '#d6d3d1', fontWeight: 600 }}>{title}</div>
        {note && <div style={{ fontSize: 11.5, color: noteColor || '#57534e', marginTop: 3, lineHeight: 1.45 }}>{note}</div>}
      </div>
    </div>
  )
}

// ── Live proxy preview ───────────────────────────────────────────────────────
// The one art screen in the app that had no preview at all. This is a faithful
// mock of what the renderer will lay out (title bar + cost, art window, type bar,
// rules/flavor, P-T or loyalty badge) built from the fields as they are typed —
// no server round-trip, so it is instant and works with every service down.
function CardPreview({ name, manaCost, typeLine, oracle, flavor, power, toughness, loyalty, colors, rarity }) {
  const frame = useMemo(() => {
    const c = colors || []
    if (/land/i.test(typeLine)) return { bg: '#3f3a33', edge: '#5c5346', ink: '#f5f5f4' }
    if (c.length > 1) return { bg: '#8a7635', edge: '#c8ac4e', ink: '#0c0a09' }
    const one = {
      W: { bg: '#d9d2bd', edge: '#efe8d2', ink: '#0c0a09' },
      U: { bg: '#2a6ba8', edge: '#4d92cf', ink: '#f5f5f4' },
      B: { bg: '#2c2733', edge: '#4b4356', ink: '#f5f5f4' },
      R: { bg: '#9c3520', edge: '#c8543a', ink: '#f5f5f4' },
      G: { bg: '#2c6b3f', edge: '#4a9160', ink: '#f5f5f4' },
    }[c[0]]
    if (one) return one
    if (/artifact/i.test(typeLine)) return { bg: '#4b5563', edge: '#6b7280', ink: '#f5f5f4' }
    return { bg: '#3a3632', edge: '#57534e', ink: '#f5f5f4' }
  }, [colors, typeLine])

  const badge = (power !== '' && toughness !== '') ? `${power || 0}/${toughness || 0}`
              : (loyalty !== '' && loyalty != null ? String(loyalty) : null)
  const dot = (RARITIES.find(r => r.key === rarity) || RARITIES[2]).dot

  return (
    <div style={{ position: 'sticky', top: 16 }}>
      <div style={{ fontSize: 10.5, color: '#57534e', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
        Live preview
      </div>
      <div style={{ width: 268, aspectRatio: '750 / 1050', background: frame.edge, borderRadius: 14,
                    padding: 9, boxShadow: '0 10px 34px rgba(0,0,0,0.55)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, background: frame.bg, borderRadius: 8, padding: 7,
                      display: 'flex', flexDirection: 'column', gap: 5, minHeight: 0 }}>
          {/* Title bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(0,0,0,0.16)',
                        borderRadius: 5, padding: '4px 7px', minHeight: 24 }}>
            <span style={{ flex: 1, fontSize: 11.5, fontWeight: 700, color: frame.ink,
                           overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {name || <span style={{ opacity: 0.45 }}>Card name</span>}
            </span>
            {manaCost ? <ManaCost cost={normalizeManaCost(manaCost)} size={13} /> : null}
          </div>
          {/* Art window */}
          <div style={{ aspectRatio: '1152 / 768', background: '#0c0a09', borderRadius: 4,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: '#44403c', fontSize: 10.5, textAlign: 'center', padding: 8 }}>
            AI art goes here
          </div>
          {/* Type bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(0,0,0,0.16)',
                        borderRadius: 5, padding: '3px 7px', minHeight: 20 }}>
            <span style={{ flex: 1, fontSize: 10, color: frame.ink, overflow: 'hidden',
                           textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {typeLine || <span style={{ opacity: 0.45 }}>Type line</span>}
            </span>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: dot, flexShrink: 0 }} />
          </div>
          {/* Text box */}
          <div style={{ flex: 1, minHeight: 0, background: 'rgba(255,255,255,0.9)', borderRadius: 5,
                        padding: '6px 8px', position: 'relative', overflow: 'hidden' }}>
            <div style={{ fontSize: 9.5, color: '#1c1917', lineHeight: 1.4, whiteSpace: 'pre-wrap',
                          maxHeight: '100%', overflow: 'hidden' }}>
              {oracle}
              {oracle && flavor ? <div style={{ height: 1, background: '#a8a29e', margin: '5px 6px' }} /> : null}
              {flavor ? <span style={{ fontStyle: 'italic', color: '#57534e' }}>{flavor}</span> : null}
              {!oracle && !flavor && <span style={{ color: '#a8a29e' }}>Rules text</span>}
            </div>
            {badge && (
              <div style={{ position: 'absolute', right: -2, bottom: -2, background: frame.edge,
                            border: `1px solid ${frame.bg}`, borderRadius: 5, padding: '2px 10px',
                            fontSize: 12, fontWeight: 800, color: frame.ink }}>
                {badge}
              </div>
            )}
          </div>
        </div>
      </div>
      <div style={{ width: 268, fontSize: 10.5, color: '#57534e', marginTop: 8, lineHeight: 1.5 }}>
        A sketch of the layout, not the final render — the real proxy uses the
        Magic frames, fonts and your generated art.
      </div>
    </div>
  )
}

export default function StepSingleCard({ genSettings, onGenerate, onBack, initial }) {
  const init = initial || {}

  // ── Card definition ──
  const [name, setName]           = useState(init.name || '')
  const [manaCost, setManaCost]   = useState(init.mana_cost || '')
  const [typeLine, setTypeLine]   = useState(init.type_line || '')
  const [oracle, setOracle]       = useState(init.oracle_text || '')
  const [flavor, setFlavor]       = useState(init.flavor_text || '')
  const [power, setPower]         = useState(init.power || '')
  const [toughness, setToughness] = useState(init.toughness || '')
  const [loyalty, setLoyalty]     = useState(init.loyalty || '')
  const [rarity, setRarity]       = useState(init.rarity || 'rare')
  const [colors, setColors]       = useState(init.colors || [])   // [] = derive from mana cost

  // ── Theming ──
  const [themeMode, setThemeMode]     = useState(init.theme_mode || 'author')   // author | full
  const [setting, setSetting]         = useState(init.setting || '')
  const [moods, setMoods]             = useState(init.moods || [])
  const [genres, setGenres]           = useState(init.genres || [])
  const [lighting, setLighting]       = useState(init.lighting || [])
  const [inspiration, setInspiration] = useState(init.inspiration || '')
  const [creativity, setCreativity]   = useState(init.creativity || 'balanced')
  const [subject, setSubject]         = useState(init.commander_prompt || '')

  // ── Art prompt ──
  const [artPromptMode, setArtPromptMode] = useState(init.art_prompt_mode || 'auto')  // auto | custom
  const [artPrompt, setArtPrompt]         = useState(init.art_prompt || '')

  // ── Art & frame ──
  // Art generation defaults ON: this screen exists to make a card WITH art, and
  // defaulting it off meant the obvious path — fill in the card, press Generate —
  // produced a proxy with an empty black art box and no explanation.
  const [generateArt, setGenerateArt] = useState(init.generate_art !== undefined ? !!init.generate_art : true)
  const [artStyle, setArtStyle]       = useState(init.art_style || 'mtg_fantasy')
  const [modelSpeed, setModelSpeed]   = useState(init.model_speed || 'quality')
  const [checkpoint, setCheckpoint]   = useState(init.checkpoint || '')
  const [llmModel, setLlmModel]       = useState(init.llm_model || '')
  const [frameStyle, setFrameStyle]   = useState(init.frame_style || 'builtin')
  const [borderTheme, setBorderTheme] = useState(init.border_theme || '')
  const [customPips, setCustomPips]   = useState(!!init.custom_pips)
  const [emblem, setEmblem]           = useState(init.emblem_prompt || '')

  // ── Face ──
  const [facePhotos, setFacePhotos]   = useState([])   // {file, url}
  const [faceGender, setFaceGender]   = useState(init.face_gender || 'either')
  const [faceUploading, setFaceUploading] = useState(false)
  const [dragOver, setDragOver]       = useState(false)
  const fileRef = useRef(null)

  // ── "Proxy a real card" ──
  const [lookupQ, setLookupQ]         = useState('')
  const [lookupSug, setLookupSug]     = useState([])
  const [showLookupSug, setShowLookupSug] = useState(false)
  const [activeIdx, setActiveIdx]     = useState(-1)
  const [lookupBusy, setLookupBusy]   = useState(false)
  const [lookupErr, setLookupErr]     = useState('')
  const [sourceCard, setSourceCard]   = useState(null)   // {name, image, snapshot}
  const lookupDebounce = useRef(null)
  const lookupBoxRef   = useRef(null)

  // ── Catalogs / service health ──
  const [stylePresets, setStylePresets] = useState([])
  const [frameStyles, setFrameStyles]   = useState([])
  const [checkpoints, setCheckpoints]   = useState([])
  const [llmModels, setLlmModels]       = useState([])
  const [health, setHealth]             = useState(null)   // {comfyui, llm, llm_backend}
  const [submitting, setSubmitting]     = useState(false)
  const [error, setError]               = useState('')
  const [touched, setTouched]           = useState(false)

  useEffect(() => {
    if (lookupDebounce.current) clearTimeout(lookupDebounce.current)
    const term = lookupQ.trim()
    if (term.length < 2) { setLookupSug([]); setActiveIdx(-1); return }
    lookupDebounce.current = setTimeout(() => {
      fetch(`/api/collection/suggest?q=${encodeURIComponent(term)}`)
        .then(r => r.json()).then(d => { setLookupSug(d.suggestions || []); setActiveIdx(-1) })
        .catch(() => setLookupSug([]))
    }, 200)
    return () => lookupDebounce.current && clearTimeout(lookupDebounce.current)
  }, [lookupQ])

  // Dismiss the suggestion list on an outside click (StepCommander's pattern) —
  // a blur timeout alone raced with the click that was trying to pick an item.
  useEffect(() => {
    function onDown(e) {
      if (lookupBoxRef.current && !lookupBoxRef.current.contains(e.target)) setShowLookupSug(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  useEffect(() => {
    let dead = false
    fetch('/api/art-styles').then(r => r.ok ? r.json() : null).then(d => { if (!dead && d) setStylePresets(d) }).catch(() => {})
    fetch('/api/frame-styles').then(r => r.ok ? r.json() : null).then(d => { if (!dead && d) setFrameStyles(d.styles || []) }).catch(() => {})
    fetch('/api/checkpoints').then(r => r.ok ? r.json() : null).then(d => {
      if (dead || !d) return
      setCheckpoints(Array.isArray(d) ? d : (d.checkpoints || []))
    }).catch(() => {})
    fetch('/api/llm-models').then(r => r.ok ? r.json() : null).then(d => { if (!dead && d) setLlmModels(d) }).catch(() => {})
    return () => { dead = true }
  }, [])

  // Live service health. Without this the screen looked fully functional with
  // ComfyUI and the LLM both down — you built, waited, and got a text-only card.
  useEffect(() => {
    let dead = false
    const poll = () => fetch('/api/health').then(r => r.ok ? r.json() : null)
      .then(d => { if (!dead && d) setHealth(d) }).catch(() => {})
    poll()
    const t = setInterval(poll, 15000)
    return () => { dead = true; clearInterval(t) }
  }, [])

  const comfyDown = health && health.comfyui !== 'up'
  const llmDown   = health && health.llm !== 'up'
  // Does this configuration actually need the LLM? Mirrors server._run_card_build.
  const usesLlm   = themeMode === 'full' || !(artPromptMode === 'custom' && artPrompt.trim())

  // P/T is a property of the card's TYPES, not of the word "creature" — Vehicles
  // print a power and toughness too, and gating on /creature/ silently dropped them.
  const hasPT   = /\b(creature|vehicle)\b/i.test(typeLine)
  const isPlaneswalker = /planeswalker/i.test(typeLine)
  const toggleColor = (c) => setColors(colors.includes(c) ? colors.filter(x => x !== c) : [...colors, c])

  const nameOk = name.trim().length > 0
  const typeOk = typeLine.trim().length > 0
  const canGenerate = nameOk && typeOk

  // The prefilled card is only "the real card" until the user changes something.
  const edited = sourceCard && (
    name !== sourceCard.snapshot.name || manaCost !== sourceCard.snapshot.manaCost ||
    typeLine !== sourceCard.snapshot.typeLine || oracle !== sourceCard.snapshot.oracle)

  async function loadRealCard(cardName) {
    const nm = (cardName || lookupQ).trim()
    if (!nm) return
    setLookupBusy(true); setLookupErr(''); setShowLookupSug(false)
    try {
      const r = await fetch(`/api/card-lookup?name=${encodeURIComponent(nm)}`)
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setLookupErr(d.detail || `No card found matching “${nm}”`)
        return
      }
      const c = await r.json()
      // Double-faced / split cards come back with "//" in the name and, for a DFC,
      // no printed mana cost or type on the combined object. Take the FRONT face and
      // say so, instead of prefilling blank fields under a green "success" banner.
      const multi = (c.name || '').includes('//')
      const front = (v) => (v || '').split('//')[0].trim()
      setName(multi ? front(c.name) : c.name)
      setManaCost(front(c.mana_cost))
      setTypeLine(front(c.type_line))
      setOracle((c.oracle_text || '').split('\n//\n')[0])
      setFlavor(c.flavor_text || '')
      setPower(c.power || ''); setToughness(c.toughness || ''); setLoyalty(c.loyalty || '')
      if (c.rarity && RARITIES.some(r2 => r2.key === c.rarity)) setRarity(c.rarity)
      setColors(c.colors || [])
      // Keep the printed name + rules exactly as-is; only the art is new.
      setThemeMode('author')
      setSourceCard({
        name: c.name, image: c.image, multiface: multi,
        snapshot: { name: multi ? front(c.name) : c.name, manaCost: front(c.mana_cost),
                    typeLine: front(c.type_line), oracle: (c.oracle_text || '').split('\n//\n')[0] },
      })
      setLookupQ('')
    } catch {
      setLookupErr('Lookup failed — is the server running?')
    } finally {
      setLookupBusy(false)
    }
  }

  function onLookupKey(e) {
    if (!showLookupSug || !lookupSug.length) {
      if (e.key === 'Enter') { e.preventDefault(); loadRealCard() }
      return
    }
    if (e.key === 'ArrowDown')      { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, lookupSug.length - 1)) }
    else if (e.key === 'ArrowUp')   { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Escape')    { setShowLookupSug(false) }
    else if (e.key === 'Enter')     { e.preventDefault(); loadRealCard(activeIdx >= 0 ? lookupSug[activeIdx] : undefined) }
  }

  function clearSourceCard() {
    // Only detach the "proxying" badge — the fields stay. Wiping every field was a
    // trap: the button read "Clear" next to the banner, and pressing it deleted
    // edits the user had just made on top of the looked-up card.
    setSourceCard(null)
  }

  function addFaceFiles(files) {
    const arr = Array.from(files || []).filter(f => f.type.startsWith('image/'))
    setFacePhotos(prev => [...prev, ...arr.map(f => ({ file: f, url: URL.createObjectURL(f) }))])
  }

  async function uploadFaceIfAny() {
    if (!facePhotos.length) return null
    setFaceUploading(true)
    try {
      const form = new FormData()
      facePhotos.forEach(p => form.append('files', p.file))
      const res = await fetch('/api/upload-face', { method: 'POST', body: form })
      if (!res.ok) throw new Error(`Face upload failed (HTTP ${res.status})`)
      const data = await res.json()
      return data.face_key
    } finally {
      setFaceUploading(false)
    }
  }

  async function handleGenerate() {
    setError(''); setTouched(true)
    if (!canGenerate) {
      setError(!nameOk ? 'Give the card a name.' : 'Give the card a type line.')
      return
    }
    setSubmitting(true)
    try {
      let faceKey = null
      // A face is only ever applied to generated art — don't make the user wait on
      // an upload that can't be used.
      if (generateArt) {
        try { faceKey = await uploadFaceIfAny() }
        catch (e) { setError(String(e.message || e)); setSubmitting(false); return }
      }

      const payload = {
        card: {
          name: name.trim(),
          mana_cost: normalizeManaCost(manaCost),
          type_line: typeLine.trim(),
          oracle_text: oracle,
          flavor_text: flavor,
          power: hasPT && power !== '' ? power : null,
          toughness: hasPT && toughness !== '' ? toughness : null,
          loyalty: isPlaneswalker && loyalty !== '' ? loyalty : null,
          rarity,
          colors: colors.length ? colors : null,
        },
        theme_mode: themeMode,
        art_prompt_mode: artPromptMode,
        art_prompt: artPromptMode === 'custom' ? artPrompt : '',
        art_theme: composeVision(setting, moods, genres, lighting, inspiration),
        theme_spec: { setting, moods, genres, lighting, inspiration },
        creativity,
        commander_prompt: subject,
        emblem_prompt: emblem,
        art_style: artStyle,
        generate_art: generateArt,
        model_speed: modelSpeed,
        checkpoint: checkpoint || null,
        llm_model: llmModel || null,
        border_theme: borderTheme || '',
        frame_style: frameStyle || 'builtin',
        custom_pips: customPips,
        face_key: faceKey || null,
        face_gender: faceGender,
        gen_settings: toGenSettingsPayload(genSettings.values),
      }
      await onGenerate(payload)
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setSubmitting(false)
    }
  }

  const busy = submitting || faceUploading
  const selectedStyle = stylePresets.find(p => p.key === artStyle)

  return (
    <div style={s.wrap}>
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        <div style={{ ...s.card, flex: 1, minWidth: 0 }}>
          <div style={s.title}>Single Card</div>
          <div style={s.sub}>Design one custom card — or proxy a real one — then generate AI art and a finished proxy.</div>

          {/* ── Service health ─────────────────────────────────────────────── */}
          {health && (comfyDown || (llmDown && usesLlm)) && (
            <div style={{ marginBottom: 18, padding: '10px 14px', borderRadius: 10,
                          background: '#1c1408', border: '1px solid #a16207', fontSize: 12.5,
                          color: '#fcd34d', lineHeight: 1.6 }}>
              {comfyDown && generateArt && (
                <div>⚠ <b>ComfyUI is not running</b> — start it (manage.bat → 9) or this card will render
                  with an empty art box.</div>
              )}
              {llmDown && usesLlm && (
                <div>⚠ <b>The theming LLM is not running</b> — start <code>E:\llama\start-llama-swap.bat</code>.
                  Without it the art prompt is written from your card's own fields instead of by the AI
                  {themeMode === 'full' ? ', and the card keeps the name and flavor you typed' : ''}.</div>
              )}
            </div>
          )}

          {/* 1 — Card definition */}
          <Group num={1} title="Card" sub="what it says">
            {/* Proxy a REAL card: look it up, keep its real rules text, new art. */}
            <div ref={lookupBoxRef} style={{ marginBottom: 14, padding: 12, borderRadius: 10,
                          background: '#0c0a09', border: '1px solid #292524' }}>
              <div style={{ fontSize: 12.5, color: '#a8a29e', marginBottom: 8 }}>
                <b style={{ color: '#eab308' }}>Proxying a real card?</b> Look it up to fill in its
                real name, cost, type and rules text — then generate new art for it.
                Or just type your own card below.
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ flex: 1, position: 'relative' }}>
                  <input
                    style={s.input}
                    value={lookupQ}
                    role="combobox"
                    aria-expanded={showLookupSug && lookupSug.length > 0}
                    aria-autocomplete="list"
                    onChange={e => { setLookupQ(e.target.value); setShowLookupSug(true) }}
                    onKeyDown={onLookupKey}
                    onFocus={() => setShowLookupSug(true)}
                    placeholder="Search a real card — e.g. Lightning Bolt"
                  />
                  {showLookupSug && lookupSug.length > 0 && (
                    <div role="listbox" style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 30,
                                  marginTop: 4, background: '#1c1917', border: '1px solid #292524',
                                  borderRadius: 8, maxHeight: 240, overflowY: 'auto',
                                  boxShadow: '0 6px 20px rgba(0,0,0,0.5)' }}>
                      {lookupSug.map((sg, i) => (
                        <div key={sg} role="option" aria-selected={i === activeIdx}
                          onMouseDown={e => { e.preventDefault(); loadRealCard(sg) }}
                          onMouseEnter={() => setActiveIdx(i)}
                          style={{ padding: '7px 12px', fontSize: 13.5, cursor: 'pointer',
                                   background: i === activeIdx ? '#2a2420' : 'transparent',
                                   color: i === activeIdx ? '#fde047' : '#f5f5f4' }}>
                          {sg}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <button type="button" onClick={() => loadRealCard()} disabled={lookupBusy || !lookupQ.trim()}
                  style={{ padding: '9px 16px', borderRadius: 8, border: '1px solid #a16207',
                           background: '#1c1408', color: '#eab308', fontWeight: 700, fontSize: 13,
                           fontFamily: 'inherit', whiteSpace: 'nowrap',
                           cursor: lookupBusy || !lookupQ.trim() ? 'default' : 'pointer',
                           opacity: lookupBusy || !lookupQ.trim() ? 0.5 : 1 }}>
                  {lookupBusy ? '…' : 'Look up'}
                </button>
              </div>
              {lookupErr && <div style={s.err}>{lookupErr}</div>}
              {sourceCard && (
                <div style={{ marginTop: 10, padding: 10, borderRadius: 8, display: 'flex',
                              alignItems: 'center', gap: 10,
                              background: edited ? '#1c1408' : '#0c1a0c',
                              border: `1px solid ${edited ? '#a16207' : '#166534'}` }}>
                  {sourceCard.image && (
                    <img src={sourceCard.image} alt="" style={{ width: 40, borderRadius: 4, flexShrink: 0 }} />
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: edited ? '#fcd34d' : '#4ade80' }}>
                      {edited ? `✎ Based on ${sourceCard.name} — you've edited it` : `✓ Proxying ${sourceCard.name}`}
                    </div>
                    <div style={{ fontSize: 11, color: '#78716c' }}>
                      {sourceCard.multiface
                        ? 'Multi-faced card — only the FRONT face was filled in.'
                        : 'Real rules text kept verbatim. Edit anything below, then generate new art.'}
                    </div>
                  </div>
                  <button type="button" onClick={clearSourceCard}
                    style={{ padding: '4px 10px', borderRadius: 8, border: '1px solid #292524',
                             background: '#0c0a09', color: '#a8a29e', fontSize: 11.5,
                             fontFamily: 'inherit', cursor: 'pointer', flexShrink: 0 }}>
                    Detach
                  </button>
                </div>
              )}
            </div>

            <div style={s.row}>
              <div style={{ ...s.field, minWidth: '100%' }}>
                <label style={s.label} htmlFor="sc-name">Card name</label>
                <input id="sc-name" maxLength={LIMITS.name}
                  style={{ ...s.input, ...(touched && !nameOk ? s.inputBad : {}) }}
                  value={name} onChange={e => setName(e.target.value)}
                  placeholder="e.g. Seraphine, Dawnward Flame" />
                {touched && !nameOk && <div style={s.err}>Every card needs a name.</div>}
              </div>
            </div>
            <div style={s.row}>
              <div style={s.field}>
                <label style={s.label} htmlFor="sc-cost">
                  Mana cost{' '}
                  {manaCost && <span style={{ marginLeft: 8 }}><ManaCost cost={normalizeManaCost(manaCost)} size={16} /></span>}
                </label>
                <input id="sc-cost" maxLength={LIMITS.mana_cost} style={s.input} value={manaCost}
                  onChange={e => setManaCost(e.target.value)} placeholder="{2}{W}{U}  —  or just 2WU" />
                {manaCost && !manaCost.includes('{') && normalizeManaCost(manaCost) !== manaCost && (
                  <div style={{ ...s.hint, marginTop: 6, marginBottom: 0, color: '#78716c' }}>
                    Reads as <b style={{ color: '#a8a29e' }}>{normalizeManaCost(manaCost)}</b>
                  </div>
                )}
                {manaCost && !manaCost.includes('{') && normalizeManaCost(manaCost) === manaCost && (
                  <div style={s.warn}>That isn't a mana cost — use symbols like {'{2}{W}{U}'} (or 2WU).</div>
                )}
                <div style={s.exGrid}>
                  {MANA_EXAMPLES.map(m => <button key={m} type="button" style={s.exBtn} onClick={() => setManaCost(m)}>{m}</button>)}
                </div>
              </div>
              <div style={s.field}>
                <label style={s.label}>Rarity <span style={{ color: '#57534e' }}>(sets the set-symbol metal)</span></label>
                <div style={s.chipGrid}>
                  {RARITIES.map(r => (
                    <button key={r.key} type="button" style={{ ...s.chip(rarity === r.key), display: 'inline-flex', alignItems: 'center', gap: 6 }}
                      onClick={() => setRarity(r.key)}>
                      <span style={{ width: 9, height: 9, borderRadius: '50%', background: r.dot,
                                     border: '1px solid rgba(0,0,0,0.35)' }} />
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div style={s.row}>
              <div style={{ ...s.field, minWidth: '100%' }}>
                <label style={s.label} htmlFor="sc-type">Type line</label>
                <input id="sc-type" maxLength={LIMITS.type_line}
                  style={{ ...s.input, ...(touched && !typeOk ? s.inputBad : {}) }}
                  value={typeLine} onChange={e => setTypeLine(e.target.value)}
                  placeholder="Legendary Creature — Human Knight" />
                {touched && !typeOk && <div style={s.err}>The type line sets the frame and the card's kind — it can't be blank.</div>}
                <div style={s.exGrid}>
                  {TYPE_EXAMPLES.map(t => <button key={t} type="button" style={s.exBtn} onClick={() => setTypeLine(t)}>{t}</button>)}
                </div>
              </div>
            </div>
            <div style={s.row}>
              <div style={{ ...s.field, minWidth: '100%' }}>
                <label style={s.label} htmlFor="sc-rules">Rules text</label>
                <textarea id="sc-rules" maxLength={LIMITS.oracle_text} style={s.textarea} value={oracle}
                  onChange={e => setOracle(e.target.value)}
                  placeholder="Flying, vigilance&#10;Whenever Seraphine attacks, create a 1/1 white Spirit creature token with flying." />
              </div>
            </div>
            <div style={s.row}>
              <div style={{ ...s.field, minWidth: '100%' }}>
                <label style={s.label} htmlFor="sc-flavor">Flavor text <span style={{ color: '#57534e' }}>(optional — the AI writes one if you leave it blank)</span></label>
                <textarea id="sc-flavor" maxLength={LIMITS.flavor_text} style={{ ...s.textarea, minHeight: 50 }}
                  value={flavor} onChange={e => setFlavor(e.target.value)}
                  placeholder="“Dawn answers only to the worthy.”" />
              </div>
            </div>
            {(hasPT || isPlaneswalker) && (
              <div style={s.row}>
                {hasPT && <>
                  <div style={s.field}>
                    <label style={s.label} htmlFor="sc-pow">Power</label>
                    <input id="sc-pow" style={s.input} value={power} onChange={e => setPower(e.target.value)} placeholder="3" />
                  </div>
                  <div style={s.field}>
                    <label style={s.label} htmlFor="sc-tou">Toughness</label>
                    <input id="sc-tou" style={s.input} value={toughness} onChange={e => setToughness(e.target.value)} placeholder="4" />
                  </div>
                </>}
                {isPlaneswalker && (
                  <div style={s.field}>
                    <label style={s.label} htmlFor="sc-loy">Starting loyalty</label>
                    <input id="sc-loy" style={s.input} value={loyalty} onChange={e => setLoyalty(e.target.value)} placeholder="4" />
                    <div style={{ ...s.hint, marginTop: 6, marginBottom: 0 }}>
                      Printed in the bottom-right badge. The proxy frame has no per-ability
                      loyalty boxes — write the abilities as rules text (“+1: …”).
                    </div>
                  </div>
                )}
              </div>
            )}
            <div>
              <label style={s.label}>Color identity <span style={{ color: '#57534e' }}>(optional — auto-derived from the mana cost)</span></label>
              <div style={s.chipGrid}>
                {WUBRG.map(c => <button key={c} type="button" style={s.chip(colors.includes(c))} onClick={() => toggleColor(c)}>{c}</button>)}
              </div>
            </div>
          </Group>

          {/* 2 — Art */}
          <Group num={2} title="Art" sub="what it looks like">
            <Toggle
              on={generateArt}
              onChange={setGenerateArt}
              title="Generate AI art with ComfyUI"
              noteColor={generateArt && comfyDown ? '#fbbf24' : undefined}
              note={
                !generateArt
                  ? 'Off — the proxy renders with an empty art box. Turn this on to get a real card.'
                  : comfyDown
                    ? '⚠ ComfyUI is not reachable at :8188 — start it first.'
                    : health
                      ? '✓ ComfyUI is running.'
                      : 'Checking ComfyUI…'
              }
            />

            {generateArt && stylePresets.length > 0 && (
              <div style={{ marginBottom: 18 }}>
                <label style={s.label}>Art style</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(132px, 1fr))', gap: 8 }}>
                  {stylePresets.map(st => {
                    const on = artStyle === st.key
                    const statusColor = st.ready ? '#4ade80' : st.partial ? '#eab308' : '#78716c'
                    const statusLabel = st.ready ? '✓ Ready' : st.partial ? '~ Partial' : '○ Prompt-only'
                    const reqType = (st.required_checkpoint_type || '').toUpperCase()
                    return (
                      <button key={st.key} type="button" onClick={() => setArtStyle(st.key)}
                        style={{ padding: '9px 10px 8px', borderRadius: 10, textAlign: 'left',
                                 background: on ? '#1a1208' : '#0c0a09',
                                 border: `1px solid ${on ? '#ca8a04' : '#292524'}`,
                                 fontFamily: 'inherit', cursor: 'pointer' }}>
                        <div style={{ fontSize: 16, marginBottom: 3 }}>{st.icon}</div>
                        <div style={{ fontSize: 11.5, fontWeight: 700, lineHeight: 1.2, marginBottom: 2,
                                      color: on ? '#eab308' : '#a8a29e' }}>{st.label || st.key}</div>
                        <div style={{ fontSize: 9.5, color: statusColor }}>{statusLabel}</div>
                        {reqType && <div style={{ fontSize: 9, color: '#78716c', marginTop: 1 }}>{reqType} required</div>}
                      </button>
                    )
                  })}
                </div>
                {selectedStyle?.description && (
                  <div style={{ marginTop: 8, fontSize: 12, color: '#57534e', lineHeight: 1.5 }}>
                    {selectedStyle.description}
                  </div>
                )}
              </div>
            )}

            {generateArt && (
              <div style={{ marginBottom: 16 }}>
                <label style={s.label}>Render speed</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {SPEEDS.map(sp => (
                    <button key={sp.key} type="button" onClick={() => { setModelSpeed(sp.key); setCheckpoint('') }}
                      title={sp.note}
                      style={{ ...s.chip(modelSpeed === sp.key), padding: '6px 12px' }}>
                      {sp.label}
                    </button>
                  ))}
                </div>
                <div style={{ ...s.hint, marginTop: 8, marginBottom: 0 }}>
                  {(SPEEDS.find(x => x.key === modelSpeed) || {}).note}
                  {checkpoint && <> · overridden by the pinned checkpoint <b style={{ color: '#a8a29e' }}>{checkpoint}</b></>}
                </div>
              </div>
            )}

            {/* Art prompt */}
            <label style={s.label}>Who writes the art prompt?</label>
            <div style={s.segWrap}>
              <button type="button" style={s.seg(artPromptMode === 'auto')} onClick={() => setArtPromptMode('auto')}>AI writes it</button>
              <button type="button" style={s.seg(artPromptMode === 'custom')} onClick={() => setArtPromptMode('custom')}>I write it</button>
            </div>
            <div style={s.hint}>
              {artPromptMode === 'auto'
                ? 'The AI turns your card and the world below into a scene that depicts it.'
                : 'Your prompt goes to the image model verbatim — the world settings below are ignored for art.'}
            </div>
            {artPromptMode === 'custom' && (
              <textarea style={s.textarea} value={artPrompt} onChange={e => setArtPrompt(e.target.value)}
                maxLength={2000}
                placeholder="digital painting, a radiant knight raising a flaming greatsword atop a ruined cathedral, golden light…" />
            )}
          </Group>

          {/* 3 — World & vision */}
          <Group num={3} title="World" sub={artPromptMode === 'custom' && themeMode === 'author' ? 'not used with your own prompt' : 'the setting the art lives in'}>
            <label style={s.label}>How should the card be written?</label>
            <div style={s.segWrap}>
              <button type="button" style={s.seg(themeMode === 'author')} onClick={() => setThemeMode('author')}>I author it · AI does art</button>
              <button type="button" style={s.seg(themeMode === 'full')} onClick={() => setThemeMode('full')}>AI themes everything</button>
            </div>
            <div style={s.hint}>
              {themeMode === 'author'
                ? 'Your name and rules text are kept verbatim; the AI only writes the art.'
                : 'The AI renames the card and writes new flavor to fit the world below. Your rules text is kept.'}
            </div>

            {artPromptMode === 'custom' && themeMode === 'author' ? (
              <div style={{ padding: '12px 14px', borderRadius: 10, background: '#0c0a09',
                            border: '1px dashed #44403c', fontSize: 12.5, color: '#78716c', lineHeight: 1.6 }}>
                You wrote the card and you're writing the art prompt, so nothing here would be used.
                Switch “Who writes the art prompt?” back to <b style={{ color: '#a8a29e' }}>AI writes it</b> to
                describe a world instead.
              </div>
            ) : (
              <>
                <label style={s.label} htmlFor="sc-setting">Setting / world</label>
                <textarea id="sc-setting" style={{ ...s.textarea, minHeight: 56 }} value={setting}
                  onChange={e => setSetting(e.target.value)}
                  placeholder="dark gothic necromancer city; volcanic dragon empire; …" />
                <div style={{ height: 12 }} />
                <label style={s.label}>Genre</label>
                <Chips options={VISION_GENRES} value={genres} onChange={setGenres} />
                <label style={s.label}>Mood</label>
                <Chips options={VISION_MOODS} value={moods} onChange={setMoods} />
                <label style={s.label}>Lighting / atmosphere</label>
                <Chips options={VISION_LIGHTING} value={lighting} onChange={setLighting} />
                <div style={s.row}>
                  <div style={s.field}>
                    <label style={s.label} htmlFor="sc-insp">Inspiration (optional)</label>
                    <input id="sc-insp" style={s.input} value={inspiration} onChange={e => setInspiration(e.target.value)} placeholder="Berserk, Studio Ghibli, …" />
                  </div>
                  <div style={s.field}>
                    <label style={s.label} htmlFor="sc-creativity">Creativity</label>
                    <select id="sc-creativity" style={s.input} value={creativity} onChange={e => setCreativity(e.target.value)}>
                      <option value="faithful">Faithful (stick to my vision)</option>
                      <option value="balanced">Balanced</option>
                      <option value="imaginative">Imaginative (add detail)</option>
                    </select>
                  </div>
                </div>
                <label style={s.label} htmlFor="sc-subject">Subject appearance (optional)</label>
                <textarea id="sc-subject" style={{ ...s.textarea, minHeight: 50 }} value={subject}
                  onChange={e => setSubject(e.target.value)}
                  placeholder="silver-haired knight in radiant plate, broken halo, holding a flaming greatsword" />
              </>
            )}
          </Group>

          {/* 4 — Face */}
          {generateArt && (
            <Group num={4} title="Face" sub="optional likeness">
              <div style={{ fontSize: 12, color: '#78716c', marginBottom: 10 }}>
                Upload photos of a person to put their likeness in the art. Several angles of the
                same person blend into a more robust match than one photo.
              </div>
              <input ref={fileRef} type="file" accept="image/*" multiple style={{ display: 'none' }}
                     onChange={e => addFaceFiles(e.target.files)} />
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={e => { e.preventDefault(); setDragOver(false); addFaceFiles(e.dataTransfer.files) }}
                onClick={() => fileRef.current?.click()}
                style={{ padding: 16, borderRadius: 10, cursor: 'pointer', textAlign: 'center',
                         background: dragOver ? '#1c1408' : '#0c0a09',
                         border: `1px dashed ${dragOver ? '#ca8a04' : '#44403c'}` }}>
                <div style={{ fontSize: 13, color: '#a8a29e' }}>📷 Drop photos here, or click to choose</div>
              </div>
              {facePhotos.length > 0 && (
                <>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
                    {facePhotos.map((p, i) => (
                      <div key={i} style={{ position: 'relative' }}>
                        <img src={p.url} alt="" style={{ width: 52, height: 52, borderRadius: 6, objectFit: 'cover', border: '1px solid #44403c', display: 'block' }} />
                        <button type="button" aria-label="Remove photo"
                          onClick={() => setFacePhotos(prev => prev.filter((_, j) => j !== i))}
                          style={{ position: 'absolute', top: -6, right: -6, width: 18, height: 18,
                                   borderRadius: '50%', border: '1px solid #44403c', background: '#1c1917',
                                   color: '#a8a29e', fontSize: 10, cursor: 'pointer', fontFamily: 'inherit', lineHeight: 1 }}>✕</button>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <label style={s.label}>Person's sex (helps the art):</label>
                    <div style={s.chipGrid}>
                      {['either', 'male', 'female'].map(g => (
                        <button key={g} type="button" style={s.chip(faceGender === g)} onClick={() => setFaceGender(g)}>{g}</button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </Group>
          )}

          {/* 5 — Frame & finish */}
          <Group num={generateArt ? 5 : 4} title="Frame & finish" sub="how it's printed">
            <div style={s.row}>
              <div style={s.field}>
                <label style={s.label} htmlFor="sc-frame">Frame style</label>
                <select id="sc-frame" style={s.input} value={frameStyle} onChange={e => setFrameStyle(e.target.value)}>
                  {frameStyles.map(f => (
                    <option key={f.key} value={f.key} disabled={!f.available}>
                      {f.label + (f.available ? '' : ' (needs Card Conjurer)')}
                    </option>
                  ))}
                </select>
              </div>
              <div style={s.field}>
                <label style={s.label} htmlFor="sc-border">Border decoration (optional)</label>
                <input id="sc-border" style={s.input} value={borderTheme} onChange={e => setBorderTheme(e.target.value)} placeholder="glowing arcane sigils" />
              </div>
            </div>
            <div style={s.row}>
              <div style={s.field}>
                <label style={s.label} htmlFor="sc-emblem">Set-symbol subject (optional)</label>
                <input id="sc-emblem" style={s.input} value={emblem} onChange={e => setEmblem(e.target.value)} placeholder="golden crown with rubies" />
              </div>
              <div style={s.field}>
                <label style={s.label} htmlFor="sc-ckpt">Checkpoint <span style={{ color: '#57534e' }}>(auto)</span></label>
                <select id="sc-ckpt" style={s.input} value={checkpoint} onChange={e => setCheckpoint(e.target.value)}>
                  <option value="">Auto-detect from render speed</option>
                  {checkpoints.map(c => {
                    const v = typeof c === 'string' ? c : (c.filename || c.name || c.value)
                    return <option key={v} value={v}>{v}</option>
                  })}
                </select>
              </div>
            </div>
            {usesLlm && (
              <div style={s.row}>
                <div style={s.field}>
                  <label style={s.label} htmlFor="sc-llm">Theming model <span style={{ color: '#57534e' }}>(default)</span></label>
                  <select id="sc-llm" style={s.input} value={llmModel} onChange={e => setLlmModel(e.target.value)}>
                    <option value="">Default</option>
                    {llmModels.map(m => (
                      <option key={m.key} value={m.key} disabled={m.installed === false}>
                        {(m.label || m.key) + (m.installed === false ? ' (not installed)' : '')}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
            <Toggle on={customPips} onChange={setCustomPips}
              title="Custom themed mana pips"
              note="Replaces the stock mana symbols with themed discs. Needs ComfyUI for the best silhouette." />
          </Group>

          {/* Advanced — rendered bare, exactly as StepTheme does it */}
          {genSettings && <AdvancedPanel step="theme" settings={genSettings} />}

          {error && (
            <div style={{ marginTop: 16, padding: '10px 14px', borderRadius: 10, background: '#1c0a0a',
                          border: '1px solid #7f1d1d', color: '#fca5a5', fontSize: 13 }}>
              {error}
            </div>
          )}

          <div style={s.footer}>
            <button type="button" style={s.btnBack} onClick={onBack} disabled={busy}>← Back</button>
            <button type="button"
              style={{ ...s.btnNext, ...(busy || !canGenerate ? s.btnDisabled : {}) }}
              onClick={handleGenerate} disabled={busy || !canGenerate}
              title={!canGenerate ? 'A name and a type line are required' : 'Build this card'}>
              {faceUploading ? 'Uploading…' : submitting ? 'Starting…' : '✨ Generate card'}
            </button>
          </div>
        </div>

        {/* Live preview rail — hidden on narrow screens by the flex wrap below */}
        <div style={{ flexShrink: 0 }} className="sc-preview">
          <CardPreview name={name} manaCost={manaCost} typeLine={typeLine} oracle={oracle}
            flavor={flavor} power={hasPT ? power : ''} toughness={hasPT ? toughness : ''}
            loyalty={isPlaneswalker ? loyalty : ''}
            colors={colors.length ? colors : colorsFromCost(manaCost)} rarity={rarity} />
        </div>
      </div>

      <style>{`
        @media (max-width: 900px) { .sc-preview { display: none; } }
      `}</style>
    </div>
  )
}
