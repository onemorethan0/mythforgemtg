import { useEffect, useRef, useState } from 'react'
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
  { key: 'common',   label: 'Common (black)' },
  { key: 'uncommon', label: 'Uncommon (silver)' },
  { key: 'rare',     label: 'Rare (gold)' },
  { key: 'mythic',   label: 'Mythic (bronze)' },
  { key: 'special',  label: 'Special (purple)' },
]
const WUBRG = ['W', 'U', 'B', 'R', 'G']
const MANA_EXAMPLES = ['{2}{W}{U}', '{1}{B}{B}', '{3}{R}', '{G}{G}', '{X}{U}{R}', '{4}']
const TYPE_EXAMPLES = ['Legendary Creature — Human Knight', 'Instant', 'Sorcery',
                       'Artifact — Equipment', 'Enchantment — Aura', 'Legendary Planeswalker — Hero',
                       'Land', 'Creature — Dragon']

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

const s = {
  wrap: { maxWidth: 680, width: '100%', marginTop: 16 },
  card: { background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 28 },
  title: { fontSize: 22, fontWeight: 700, color: '#eab308', marginBottom: 6, letterSpacing: '0.05em' },
  sub: { fontSize: 13, color: '#78716c', marginBottom: 20 },
  groupHead: { display: 'flex', alignItems: 'center', gap: 10, margin: '26px 0 16px' },
  groupNum: { flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: '#ca8a04', color: '#0c0a09', fontSize: 12, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' },
  groupTitle: { fontSize: 14, fontWeight: 700, color: '#eab308', letterSpacing: '0.04em', textTransform: 'uppercase', whiteSpace: 'nowrap' },
  groupRule: { flex: 1, height: 1, background: '#292524' },
  label: { fontSize: 13, color: '#a8a29e', marginBottom: 8, display: 'block' },
  input: { width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10, padding: '10px 14px', color: '#f5f5f4', fontSize: 14, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' },
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
  artRow: { display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', background: '#0c0a09', border: '1px solid #292524', borderRadius: 10, marginBottom: 16 },
  toggle: (on) => ({ width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer', position: 'relative', flexShrink: 0, background: on ? '#16a34a' : '#44403c' }),
  toggleThumb: (on) => ({ position: 'absolute', top: 2, left: on ? 18 : 2, width: 16, height: 16, background: '#fff', borderRadius: '50%', transition: 'left 0.2s' }),
  footer: { display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 28 },
  btnBack: { padding: '10px 22px', background: 'none', border: '1px solid #44403c', borderRadius: 10, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit' },
  btnNext: { padding: '10px 28px', background: 'linear-gradient(180deg,#eab308,#a16207)', border: 'none', borderRadius: 10, color: '#0c0a09', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', fontSize: 15 },
  btnDisabled: { opacity: 0.4, cursor: 'not-allowed' },
}

function Group({ num, title, children }) {
  return (
    <>
      <div style={s.groupHead}>
        <span style={s.groupNum}>{num}</span>
        <span style={s.groupTitle}>{title}</span>
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

export default function StepSingleCard({ genSettings, onGenerate, onBack }) {
  // ── Card definition ──
  const [name, setName]           = useState('')
  const [manaCost, setManaCost]   = useState('')
  const [typeLine, setTypeLine]   = useState('')
  const [oracle, setOracle]       = useState('')
  const [flavor, setFlavor]       = useState('')
  const [power, setPower]         = useState('')
  const [toughness, setToughness] = useState('')
  const [loyalty, setLoyalty]     = useState('')
  const [rarity, setRarity]       = useState('rare')
  const [colors, setColors]       = useState([])   // [] = derive from mana cost

  // ── Theming ──
  const [themeMode, setThemeMode]       = useState('author')   // author | full
  const [setting, setSetting]           = useState('')
  const [moods, setMoods]               = useState([])
  const [genres, setGenres]             = useState([])
  const [lighting, setLighting]         = useState([])
  const [inspiration, setInspiration]   = useState('')
  const [creativity, setCreativity]     = useState('balanced')
  const [subject, setSubject]           = useState('')   // commander_prompt

  // ── Art prompt ──
  const [artPromptMode, setArtPromptMode] = useState('auto')   // auto | custom
  const [artPrompt, setArtPrompt]         = useState('')

  // ── Art & frame ──
  const [generateArt, setGenerateArt] = useState(false)
  const [artStyle, setArtStyle]       = useState('mtg_fantasy')
  const [modelSpeed, setModelSpeed]   = useState('quality')
  const [checkpoint, setCheckpoint]   = useState('')
  const [llmModel, setLlmModel]       = useState('')
  const [frameStyle, setFrameStyle]   = useState('builtin')
  const [borderTheme, setBorderTheme] = useState('')
  const [customPips, setCustomPips]   = useState(false)
  const [emblem, setEmblem]           = useState('')

  // ── Face ──
  const [facePhotos, setFacePhotos]   = useState([])   // {file, url}
  const [faceGender, setFaceGender]   = useState('either')
  const [faceUploading, setFaceUploading] = useState(false)
  const fileRef = useRef(null)

  // ── "Proxy a real card": look one up and prefill every field with its real
  // printed values (rules text verbatim), then generate new art for it.
  const [lookupQ, setLookupQ]         = useState('')
  const [lookupSug, setLookupSug]     = useState([])
  const [showLookupSug, setShowLookupSug] = useState(false)
  const [lookupBusy, setLookupBusy]   = useState(false)
  const [sourceCard, setSourceCard]   = useState(null)   // {name, image} once prefilled
  const lookupDebounce = useRef(null)

  useEffect(() => {
    if (lookupDebounce.current) clearTimeout(lookupDebounce.current)
    const term = lookupQ.trim()
    if (term.length < 2) { setLookupSug([]); return }
    lookupDebounce.current = setTimeout(() => {
      fetch(`/api/collection/suggest?q=${encodeURIComponent(term)}`)
        .then(r => r.json()).then(d => setLookupSug(d.suggestions || [])).catch(() => setLookupSug([]))
    }, 200)
    return () => lookupDebounce.current && clearTimeout(lookupDebounce.current)
  }, [lookupQ])

  async function loadRealCard(cardName) {
    const nm = (cardName || lookupQ).trim()
    if (!nm) return
    setLookupBusy(true); setError(''); setShowLookupSug(false)
    try {
      const r = await fetch(`/api/card-lookup?name=${encodeURIComponent(nm)}`)
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail || `No card found matching "${nm}"`)
        return
      }
      const c = await r.json()
      // Prefill EVERY field from the real card — rules text stays verbatim.
      setName(c.name); setManaCost(c.mana_cost); setTypeLine(c.type_line)
      setOracle(c.oracle_text); setFlavor(c.flavor_text)
      setPower(c.power); setToughness(c.toughness); setLoyalty(c.loyalty)
      if (c.rarity && RARITIES.some(r2 => r2.key === c.rarity)) setRarity(c.rarity)
      setColors(c.colors || [])
      // Keep the printed name + rules exactly as-is; only the art is new.
      setThemeMode('author')
      setSourceCard({ name: c.name, image: c.image })
      setLookupQ('')
    } catch {
      setError('Lookup failed — is the server running?')
    } finally {
      setLookupBusy(false)
    }
  }

  function clearSourceCard() {
    setSourceCard(null)
    setName(''); setManaCost(''); setTypeLine(''); setOracle(''); setFlavor('')
    setPower(''); setToughness(''); setLoyalty(''); setColors([])
  }

  // ── Catalogs ──
  const [stylePresets, setStylePresets] = useState([])
  const [frameStyles, setFrameStyles]   = useState([])
  const [checkpoints, setCheckpoints]   = useState([])
  const [llmModels, setLlmModels]       = useState([])
  const [submitting, setSubmitting]     = useState(false)
  const [error, setError]               = useState('')

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

  const isCreature = /creature/i.test(typeLine)
  const isPlaneswalker = /planeswalker/i.test(typeLine)
  const toggleColor = (c) => setColors(colors.includes(c) ? colors.filter(x => x !== c) : [...colors, c])

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
    setError('')
    if (!name.trim()) { setError('Give the card a name.'); return }
    setSubmitting(true)
    try {
      let faceKey = null
      try { faceKey = await uploadFaceIfAny() }
      catch (e) { setError(String(e.message || e)); setSubmitting(false); return }

      const payload = {
        card: {
          name: name.trim(),
          mana_cost: manaCost.trim(),
          type_line: typeLine.trim(),
          oracle_text: oracle,
          flavor_text: flavor,
          power: isCreature && power !== '' ? power : null,
          toughness: isCreature && toughness !== '' ? toughness : null,
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
    } finally {
      setSubmitting(false)
    }
  }

  const busy = submitting || faceUploading

  return (
    <div style={s.wrap}>
      <div style={s.card}>
        <div style={s.title}>Single Card</div>
        <div style={s.sub}>Design one custom card, then generate AI art and a finished proxy.</div>

        {/* 1 — Card definition */}
        <Group num={1} title="Card">
          {/* Proxy a REAL card: look it up, keep its real rules text, new art. */}
          {!sourceCard ? (
            <div style={{ marginBottom: 14, padding: 12, borderRadius: 10,
                          background: '#0c0a09', border: '1px solid #292524' }}>
              <div style={{ fontSize: 12.5, color: '#a8a29e', marginBottom: 8 }}>
                <b style={{ color: '#eab308' }}>Proxying a real card?</b> Look it up to fill in its
                real name, cost, type and rules text — then generate new art for it.
                Or just type your own card below.
              </div>
              <div style={{ display: 'flex', gap: 8, position: 'relative' }}>
                <div style={{ flex: 1, position: 'relative' }}>
                  <input
                    style={{ ...s.input, width: '100%', boxSizing: 'border-box' }}
                    value={lookupQ}
                    onChange={e => { setLookupQ(e.target.value); setShowLookupSug(true) }}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); loadRealCard() } }}
                    onFocus={() => setShowLookupSug(true)}
                    onBlur={() => setTimeout(() => setShowLookupSug(false), 150)}
                    placeholder="Search a real card — e.g. Lightning Bolt"
                  />
                  {showLookupSug && lookupSug.length > 0 && (
                    <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 30,
                                  marginTop: 4, background: '#1c1917', border: '1px solid #292524',
                                  borderRadius: 8, maxHeight: 240, overflowY: 'auto',
                                  boxShadow: '0 6px 20px rgba(0,0,0,0.5)' }}>
                      {lookupSug.map(sg => (
                        <div key={sg}
                          onMouseDown={e => { e.preventDefault(); loadRealCard(sg) }}
                          style={{ padding: '7px 12px', fontSize: 13.5, color: '#f5f5f4', cursor: 'pointer' }}
                          onMouseEnter={e => e.currentTarget.style.background = '#2a2420'}
                          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
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
            </div>
          ) : (
            <div style={{ marginBottom: 14, padding: 12, borderRadius: 10, display: 'flex',
                          alignItems: 'center', gap: 12,
                          background: '#0c1a0c', border: '1px solid #166534' }}>
              {sourceCard.image && (
                <img src={sourceCard.image} alt={sourceCard.name}
                  style={{ width: 46, borderRadius: 4, flexShrink: 0 }} />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#4ade80' }}>
                  ✓ Proxying {sourceCard.name}
                </div>
                <div style={{ fontSize: 11.5, color: '#78716c' }}>
                  Real rules text kept verbatim. Edit anything below, then generate new art.
                </div>
              </div>
              <button type="button" onClick={clearSourceCard}
                style={{ padding: '5px 12px', borderRadius: 8, border: '1px solid #292524',
                         background: '#0c0a09', color: '#a8a29e', fontSize: 12,
                         fontFamily: 'inherit', cursor: 'pointer', flexShrink: 0 }}>
                Clear
              </button>
            </div>
          )}
          <div style={s.row}>
            <div style={{ ...s.field, minWidth: '100%' }}>
              <label style={s.label}>Card name</label>
              <input style={s.input} value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Seraphine, Dawnward Flame" />
            </div>
          </div>
          <div style={s.row}>
            <div style={s.field}>
              <label style={s.label}>Mana cost {manaCost && <span style={{ marginLeft: 8 }}><ManaCost cost={manaCost} size={16} /></span>}</label>
              <input style={s.input} value={manaCost} onChange={e => setManaCost(e.target.value)} placeholder="{2}{W}{U}" />
              <div style={s.exGrid}>
                {MANA_EXAMPLES.map(m => <button key={m} type="button" style={s.exBtn} onClick={() => setManaCost(m)}>{m}</button>)}
              </div>
            </div>
            <div style={s.field}>
              <label style={s.label}>Rarity</label>
              <select style={s.input} value={rarity} onChange={e => setRarity(e.target.value)}>
                {RARITIES.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
              </select>
            </div>
          </div>
          <div style={s.row}>
            <div style={{ ...s.field, minWidth: '100%' }}>
              <label style={s.label}>Type line</label>
              <input style={s.input} value={typeLine} onChange={e => setTypeLine(e.target.value)} placeholder="Legendary Creature — Human Knight" />
              <div style={s.exGrid}>
                {TYPE_EXAMPLES.map(t => <button key={t} type="button" style={s.exBtn} onClick={() => setTypeLine(t)}>{t}</button>)}
              </div>
            </div>
          </div>
          <div style={s.row}>
            <div style={{ ...s.field, minWidth: '100%' }}>
              <label style={s.label}>Rules text</label>
              <textarea style={s.textarea} value={oracle} onChange={e => setOracle(e.target.value)} placeholder="Flying, vigilance&#10;Whenever Seraphine attacks, create a 1/1 white Spirit token." />
            </div>
          </div>
          <div style={s.row}>
            <div style={{ ...s.field, minWidth: '100%' }}>
              <label style={s.label}>Flavor text (optional)</label>
              <textarea style={{ ...s.textarea, minHeight: 50 }} value={flavor} onChange={e => setFlavor(e.target.value)} placeholder="“Dawn answers only to the worthy.”" />
            </div>
          </div>
          <div style={s.row}>
            {isCreature && <>
              <div style={s.field}>
                <label style={s.label}>Power</label>
                <input style={s.input} value={power} onChange={e => setPower(e.target.value)} placeholder="3" />
              </div>
              <div style={s.field}>
                <label style={s.label}>Toughness</label>
                <input style={s.input} value={toughness} onChange={e => setToughness(e.target.value)} placeholder="4" />
              </div>
            </>}
            {isPlaneswalker && (
              <div style={s.field}>
                <label style={s.label}>Loyalty</label>
                <input style={s.input} value={loyalty} onChange={e => setLoyalty(e.target.value)} placeholder="4" />
              </div>
            )}
          </div>
          <div>
            <label style={s.label}>Color identity <span style={{ color: '#57534e' }}>(optional — auto-derived from mana cost)</span></label>
            <div style={s.chipGrid}>
              {WUBRG.map(c => <button key={c} type="button" style={s.chip(colors.includes(c))} onClick={() => toggleColor(c)}>{c}</button>)}
            </div>
          </div>
        </Group>

        {/* 2 — Theming */}
        <Group num={2} title="Theme & vision">
          <label style={s.label}>How should the card be written?</label>
          <div style={s.segWrap}>
            <button type="button" style={s.seg(themeMode === 'author')} onClick={() => setThemeMode('author')}>I author it · AI does art</button>
            <button type="button" style={s.seg(themeMode === 'full')} onClick={() => setThemeMode('full')}>AI themes everything</button>
          </div>
          <div style={{ fontSize: 11, color: '#57534e', marginBottom: 16 }}>
            {themeMode === 'author'
              ? 'Your name and rules text are kept verbatim; the AI only writes the art.'
              : 'The AI renames the card and writes new flavor to fit the world (deck-style theming).'}
          </div>

          <label style={s.label}>Setting / world</label>
          <textarea style={{ ...s.textarea, minHeight: 56 }} value={setting} onChange={e => setSetting(e.target.value)} placeholder="dark gothic necromancer city; volcanic dragon empire; …" />
          <div style={{ height: 12 }} />
          <label style={s.label}>Genre</label>
          <Chips options={VISION_GENRES} value={genres} onChange={setGenres} />
          <label style={s.label}>Mood</label>
          <Chips options={VISION_MOODS} value={moods} onChange={setMoods} />
          <label style={s.label}>Lighting / atmosphere</label>
          <Chips options={VISION_LIGHTING} value={lighting} onChange={setLighting} />
          <div style={s.row}>
            <div style={s.field}>
              <label style={s.label}>Inspiration (optional)</label>
              <input style={s.input} value={inspiration} onChange={e => setInspiration(e.target.value)} placeholder="Berserk, Studio Ghibli, …" />
            </div>
            <div style={s.field}>
              <label style={s.label}>Creativity</label>
              <select style={s.input} value={creativity} onChange={e => setCreativity(e.target.value)}>
                <option value="faithful">Faithful (stick to my vision)</option>
                <option value="balanced">Balanced</option>
                <option value="imaginative">Imaginative (add detail)</option>
              </select>
            </div>
          </div>
          <label style={s.label}>Subject appearance (optional)</label>
          <textarea style={{ ...s.textarea, minHeight: 50 }} value={subject} onChange={e => setSubject(e.target.value)} placeholder="silver-haired knight in radiant plate, broken halo, holding a flaming greatsword" />
        </Group>

        {/* 3 — Art prompt */}
        <Group num={3} title="Art prompt">
          <div style={s.segWrap}>
            <button type="button" style={s.seg(artPromptMode === 'auto')} onClick={() => setArtPromptMode('auto')}>AI writes it</button>
            <button type="button" style={s.seg(artPromptMode === 'custom')} onClick={() => setArtPromptMode('custom')}>I write it</button>
          </div>
          {artPromptMode === 'custom' && (
            <textarea style={s.textarea} value={artPrompt} onChange={e => setArtPrompt(e.target.value)}
              placeholder="digital painting, a radiant knight raising a flaming greatsword atop a ruined cathedral, golden light…" />
          )}
        </Group>

        {/* 4 — Art & frame */}
        <Group num={4} title="Art & frame">
          <div style={s.artRow}>
            <button type="button" style={s.toggle(generateArt)} onClick={() => setGenerateArt(!generateArt)}>
              <span style={s.toggleThumb(generateArt)} />
            </button>
            <span style={{ fontSize: 13, color: '#a8a29e' }}>
              Generate AI art with ComfyUI {generateArt ? '' : '(off → renders a text-only proxy)'}
            </span>
          </div>
          <div style={s.row}>
            <div style={s.field}>
              <label style={s.label}>Art style</label>
              <select style={s.input} value={artStyle} onChange={e => setArtStyle(e.target.value)}>
                {stylePresets.map(p => <option key={p.key} value={p.key}>{(p.icon ? p.icon + ' ' : '') + (p.label || p.key)}</option>)}
              </select>
            </div>
            <div style={s.field}>
              <label style={s.label}>Render speed</label>
              <select style={s.input} value={modelSpeed} onChange={e => setModelSpeed(e.target.value)}>
                <option value="quality">Quality (flux-dev)</option>
                <option value="turbo">Turbo (8-step)</option>
                <option value="fast">Fast (schnell)</option>
                <option value="sd35">SD 3.5 Large</option>
              </select>
            </div>
          </div>
          <div style={s.row}>
            <div style={s.field}>
              <label style={s.label}>Checkpoint <span style={{ color: '#57534e' }}>(auto)</span></label>
              <select style={s.input} value={checkpoint} onChange={e => setCheckpoint(e.target.value)}>
                <option value="">Auto-detect</option>
                {checkpoints.map(c => {
                  const v = typeof c === 'string' ? c : (c.filename || c.name || c.value)
                  return <option key={v} value={v}>{v}</option>
                })}
              </select>
            </div>
            <div style={s.field}>
              <label style={s.label}>LLM model <span style={{ color: '#57534e' }}>(default)</span></label>
              <select style={s.input} value={llmModel} onChange={e => setLlmModel(e.target.value)}>
                <option value="">Default</option>
                {llmModels.map(m => (
                  <option key={m.key} value={m.key} disabled={m.installed === false}>
                    {(m.label || m.key) + (m.installed === false ? ' (not installed)' : '')}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div style={s.row}>
            <div style={s.field}>
              <label style={s.label}>Frame style</label>
              <select style={s.input} value={frameStyle} onChange={e => setFrameStyle(e.target.value)}>
                {frameStyles.map(f => (
                  <option key={f.key} value={f.key} disabled={!f.available}>
                    {f.label + (f.available ? '' : ' (needs Card Conjurer)')}
                  </option>
                ))}
              </select>
            </div>
            <div style={s.field}>
              <label style={s.label}>Border decoration (optional)</label>
              <input style={s.input} value={borderTheme} onChange={e => setBorderTheme(e.target.value)} placeholder="glowing arcane sigils" />
            </div>
          </div>
          <div style={s.row}>
            <div style={s.field}>
              <label style={s.label}>Set-symbol / emblem subject (optional)</label>
              <input style={s.input} value={emblem} onChange={e => setEmblem(e.target.value)} placeholder="golden crown with rubies" />
            </div>
          </div>
          <div style={s.artRow}>
            <button type="button" style={s.toggle(customPips)} onClick={() => setCustomPips(!customPips)}>
              <span style={s.toggleThumb(customPips)} />
            </button>
            <span style={{ fontSize: 13, color: '#a8a29e' }}>Custom themed mana pips</span>
          </div>
        </Group>

        {/* 5 — Face */}
        <Group num={5} title="Add a face (optional)">
          <div style={{ fontSize: 12, color: '#78716c', marginBottom: 10 }}>
            Upload one or more photos of a person to place their likeness on the card art.
          </div>
          <input ref={fileRef} type="file" accept="image/*" multiple style={{ display: 'none' }}
                 onChange={e => addFaceFiles(e.target.files)} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <button type="button" style={{ ...s.exBtn, fontSize: 13, padding: '8px 16px' }} onClick={() => fileRef.current?.click()}>
              📷 Choose photos
            </button>
            {facePhotos.map((p, i) => (
              <img key={i} src={p.url} alt="" style={{ width: 44, height: 44, borderRadius: 6, objectFit: 'cover', border: '1px solid #44403c' }} />
            ))}
            {facePhotos.length > 0 && (
              <button type="button" style={{ ...s.exBtn }} onClick={() => setFacePhotos([])}>clear</button>
            )}
          </div>
          {facePhotos.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <label style={s.label}>Person's sex (helps the art):</label>
              <div style={s.chipGrid}>
                {['either', 'male', 'female'].map(g => (
                  <button key={g} type="button" style={s.chip(faceGender === g)} onClick={() => setFaceGender(g)}>{g}</button>
                ))}
              </div>
            </div>
          )}
        </Group>

        {/* 6 — Advanced */}
        <Group num={6} title="Advanced">
          {genSettings && <AdvancedPanel step="theme" settings={genSettings} defaultOpen={false} />}
        </Group>

        {error && <div style={{ color: '#f87171', fontSize: 13, marginTop: 16 }}>{error}</div>}

        <div style={s.footer}>
          <button type="button" style={s.btnBack} onClick={onBack} disabled={busy}>← Back</button>
          <button type="button" style={{ ...s.btnNext, ...(busy ? s.btnDisabled : {}) }} onClick={handleGenerate} disabled={busy}>
            {faceUploading ? 'Uploading…' : submitting ? 'Starting…' : '✨ Generate card'}
          </button>
        </div>
      </div>
    </div>
  )
}
