import { useEffect, useState } from 'react'
import ManaCost from './ManaCost'
import AdvancedPanel from './AdvancedPanel'

const EXAMPLES = [
  'dark gothic necromancer city',
  'ancient deep sea leviathan realm',
  'steampunk goblin industrial revolution',
  'eldritch cosmic horror space void',
  'enchanted forest fae realm',
  'volcanic dragon empire',
]

// Structured "deck vision" chip options — composed into the art-theme brief.
const VISION_GENRES = ['High Fantasy', 'Dark Fantasy', 'Sci-Fi', 'Cyberpunk', 'Post-Apocalyptic',
                       'Mythic / Legend', 'Steampunk', 'Gothic', 'Historical', 'Cosmic Horror']
const VISION_MOODS  = ['Grim', 'Heroic', 'Whimsical', 'Eerie', 'Serene', 'Epic',
                       'Gritty', 'Mysterious', 'Romantic', 'Ominous']
const VISION_LIGHTING = ['Warm / golden', 'Cold / neon', 'Muted', 'Vibrant', 'High-contrast',
                         'Pastel', 'Moody / dark', 'Ethereal glow']

// ── Ragnarok Online specific constants ────────────────────────────────────────
const RO_THEMES = [
  'Prontera castle grounds, golden spires, holy light',
  'Morroc desert ruins, sandstone sphinx, scorched dunes',
  'Geffen dark magic tower, purple arcane glow, cobblestone streets',
  'Payon bamboo forest village, cherry blossoms, warm lantern light',
  'Alberta harbor docks, stormy sea, merchant ships',
  'Niflheim underworld, eerie fog, bone architecture, twilight',
  'Lighthalzen industrial laboratory, brass pipes, alchemical glow',
  'Amatsu samurai palace, cherry blossoms, paper lanterns, moonlight',
  'Einbroch factory mines, steam vents, iron scaffolding',
  'Lutie snowfield, toy factory, soft snowfall, festive lights',
]

const RO_JOB_CLASSES = [
  {
    group: 'Novice', color: '#94a3b8',
    classes: [
      'Novice',
      'Super Novice',
    ],
  },
  {
    group: 'Swordsman', color: '#ef4444',
    classes: [
      'Swordsman',
      'Knight', 'Lord Knight', 'Rune Knight',
      'Crusader', 'Paladin', 'Royal Guard',
    ],
  },
  {
    group: 'Mage', color: '#818cf8',
    classes: [
      'Mage',
      'Wizard', 'High Wizard', 'Warlock',
      'Sage', 'Professor', 'Sorcerer',
    ],
  },
  {
    group: 'Acolyte', color: '#fbbf24',
    classes: [
      'Acolyte',
      'Priest', 'High Priest', 'Archbishop',
      'Monk', 'Champion', 'Sura',
    ],
  },
  {
    group: 'Merchant', color: '#fb923c',
    classes: [
      'Merchant',
      'Blacksmith', 'Whitesmith', 'Mechanic',
      'Alchemist', 'Creator', 'Genetic',
    ],
  },
  {
    group: 'Archer', color: '#4ade80',
    classes: [
      'Archer',
      'Hunter', 'Sniper', 'Ranger',
      'Bard', 'Clown', 'Minstrel',
      'Dancer', 'Gypsy', 'Wanderer',
    ],
  },
  {
    group: 'Thief', color: '#a78bfa',
    classes: [
      'Thief',
      'Assassin', 'Assassin Cross', 'Guillotine Cross',
      'Rogue', 'Stalker', 'Shadow Chaser',
    ],
  },
  {
    group: 'Taekwon', color: '#38bdf8',
    classes: [
      'Taekwon',
      'Star Gladiator',
      'Soul Linker',
    ],
  },
  {
    group: 'Gunslinger', color: '#f472b6',
    classes: [
      'Gunslinger',
      'Rebellion',
    ],
  },
  {
    group: 'Ninja', color: '#2dd4bf',
    classes: [
      'Ninja',
      'Kagerou',
      'Oboro',
    ],
  },
  {
    group: 'Doram', color: '#e879f9',
    classes: [
      'Summoner',
    ],
  },
]

const RO_BORDER_PRESETS = [
  { label: '🏰 Prontera Stone', kw: 'Prontera stone brickwork runes', col: '#fbbf24' },
  { label: '✦ Arcane Runes',   kw: 'glowing arcane Geffen rune sigils', col: '#818cf8' },
  { label: '🌸 Amatsu Scroll', kw: 'cherry blossom petal scroll border', col: '#f9a8d4' },
  { label: '💀 Niflheim Bone', kw: 'bone and shadow wisp underworld', col: '#a78bfa' },
  { label: '⚙ Lighthalzen',   kw: 'brass gear alchemical circuit border', col: '#22d3ee' },
  { label: '🌿 Payon Bamboo',  kw: 'bamboo and vine nature border', col: '#4ade80' },
]

const s = {
  wrap: { maxWidth: 640, width: '100%', marginTop: 16 },
  commanderBar: { display: 'flex', alignItems: 'center', gap: 16, background: '#1c1917', border: '1px solid #292524', borderRadius: 12, padding: '12px 20px', marginBottom: 20 },
  cmdImg: { width: 48, height: 48, borderRadius: 6, objectFit: 'cover' },
  cmdName: { fontSize: 15, fontWeight: 700, color: '#f5f5f4' },
  cmdSub: { fontSize: 12, color: '#78716c' },
  card: { background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 28 },
  section: { marginBottom: 24 },
  title: { fontSize: 22, fontWeight: 700, color: '#eab308', marginBottom: 6, letterSpacing: '0.05em' },
  sub: { fontSize: 13, color: '#78716c', marginBottom: 20 },
  label: { fontSize: 13, color: '#a8a29e', marginBottom: 8, display: 'block' },
  textarea: { width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10, padding: '12px 16px', color: '#f5f5f4', fontSize: 14, outline: 'none', resize: 'vertical', fontFamily: 'inherit', minHeight: 80, boxSizing: 'border-box' },
  exLabel: { fontSize: 12, color: '#57534e', margin: '14px 0 8px' },
  exGrid: { display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 },
  exBtn: { fontSize: 12, padding: '5px 12px', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 20, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit' },
  artRow: { display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', background: '#0c0a09', border: '1px solid #292524', borderRadius: 10, marginBottom: 20 },
  toggle: { width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer', transition: 'background 0.2s', position: 'relative', flexShrink: 0 },
  toggleThumb: { position: 'absolute', top: 2, width: 16, height: 16, background: '#fff', borderRadius: '50%', transition: 'left 0.2s' },
  toggleLabel: { fontSize: 13, color: '#a8a29e' },
  toggleSlow: { fontSize: 11, color: '#57534e' },
  footer: { display: 'flex', gap: 12, justifyContent: 'flex-end' },
  btnBack: { padding: '10px 22px', background: 'none', border: '1px solid #44403c', borderRadius: 10, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit' },
  btnNext: { padding: '10px 28px', background: 'linear-gradient(180deg,#eab308,#a16207)', border: 'none', borderRadius: 10, color: '#0c0a09', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', fontSize: 15 },
  btnNextDisabled: { opacity: 0.4, cursor: 'not-allowed' },
}

const EMBLEM_EXAMPLES = [
  'golden crown with rubies',
  'arcane rune glowing purple',
  'silver star rising',
  'emerald dragon crest',
  'red flame shield',
  'cat paw star rainbow',
  'bone white skull diamond',
  'ocean blue shield',
]

const BORDER_THEME_EXAMPLES = [
  'ancient stone runes',
  'icy crystalline frost',
  'fire and ember sparks',
  'golden baroque scrollwork',
  'glowing arcane sigils',
  'cyberpunk circuit traces',
  'ocean waves and droplets',
  'dark shadow wisps',
  'flowering vines and leaves',
]

export default function StepTheme({
  commander, theme, onThemeChange,
  visionMoods = [], onVisionMoodsChange,
  visionGenres = [], onVisionGenresChange,
  visionLighting = [], onVisionLightingChange,
  visionInspiration = '', onVisionInspirationChange,
  commanderPrompt, onCommanderPromptChange,
  userName, onUserNameChange,
  emblemPrompt, onEmblemPromptChange,
  customPips, onCustomPipsChange,
  borderTheme, onBorderThemeChange,
  frameStyle, onFrameStyleChange,
  commanderTribe, onCommanderTribeChange,
  artStyle, onArtStyleChange,
  tribes = [], tribalOverrides = {}, onTribalOverridesChange,
  generateArt, onGenerateArtChange,
  modelSpeed, onModelSpeedChange,
  checkpoint, onCheckpointChange,
  llmModel, onLlmModelChange,
  faceKey, faceMethod,
  crewKey, crewPrompt, onCrewPromptChange,
  genSettings,
  onNext, onBack,
}) {
  const [loading, setLoading]           = useState(false)
  const [roJobClass, setRoJobClass]     = useState('')   // currently-pinned RO job class
  const [hasSchnell, setHasSchnell]     = useState(false)
  const [hasDev, setHasDev]             = useState(false)
  const [hasSd35, setHasSd35]           = useState(false)
  const [hasSDXL, setHasSDXL]           = useState(false)
  const [comfyOffline, setComfyOffline] = useState(false)
  const [stylePresets, setStylePresets] = useState([])
  const [expandedStyle, setExpandedStyle] = useState(null)
  const [llmModels, setLlmModels]       = useState([])
  const [frameStyles, setFrameStyles]   = useState([])
  const [ccDir, setCcDir]               = useState('')
  const [ccFromEnv, setCcFromEnv]       = useState(false)
  const [ccSaving, setCcSaving]         = useState(false)
  const [ccMsg, setCcMsg]               = useState('')
  const [checkpoints, setCheckpoints]   = useState([])
  const isRO = artStyle === 'ragnarok_online'
  const setTribe = (orig, val) => onTribalOverridesChange &&
    onTribalOverridesChange({ ...tribalOverrides, [orig]: val })

  // ── Deck-vision chip helpers ──
  const toggleArr = (arr, val, on) => on && on(arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val])
  const vchip = (active) => ({
    fontSize: 11, padding: '4px 10px', borderRadius: 20, cursor: 'pointer', fontFamily: 'inherit',
    transition: 'all 0.15s',
    background: active ? '#422006' : '#0c0a09',
    border: `1px solid ${active ? '#ca8a04' : '#44403c'}`,
    color: active ? '#fde047' : '#a8a29e',
  })
  // Live preview of the composed brief sent to the art engine.
  const visionBrief = [
    (theme || '').trim(),
    visionGenres.length && 'Genre: ' + visionGenres.join(', '),
    visionMoods.length && 'Mood: ' + visionMoods.join(', '),
    visionLighting.length && 'Overall lighting and atmosphere: ' + visionLighting.join(', '),
    (visionInspiration || '').trim() && 'Inspired by ' + visionInspiration.trim(),
  ].filter(Boolean).join('. ')

  // Derived: type of the currently selected checkpoint
  const activeCheckpointType = (() => {
    if (!checkpoint || !checkpoints.length) return ''
    const ckpt = checkpoints.find(c => c.filename === checkpoint)
    return (ckpt?.type || '').toUpperCase()
  })()

  // ── Custom style builder state ──────────────────────────────────────────────
  const [showBuilder, setShowBuilder]   = useState(false)
  const [installedLoras, setInstalledLoras] = useState([])
  const [builderSaving, setBuilderSaving]   = useState(false)
  const [builderError, setBuilderError]     = useState('')
  const emptyBuilder = () => ({
    key: '', label: '', description: '', icon: '✨',
    flux_prefix: '', negative_prompt: '', style_guide_hint: '',
    themer_medium: '"digital painting," or "illustration,"',
    themer_quality: '"vivid colors, detailed" or "painterly, rich texture"',
    loras: [],
  })
  const [builder, setBuilder] = useState(emptyBuilder())
  const [editingKey, setEditingKey]     = useState(null)  // null = create, string = edit

  function refreshStyles() {
    fetch('/api/art-styles').then(r => r.ok ? r.json() : null).then(d => {
      if (d) setStylePresets(d)
    }).catch(() => {})
  }

  function openBuilder(existingPreset = null) {
    fetch('/api/comfyui/loras').then(r => r.ok ? r.json() : null).then(d => {
      if (d) setInstalledLoras(d.loras || [])
    }).catch(() => {})
    if (existingPreset && existingPreset.custom) {
      setEditingKey(existingPreset.key)
      setBuilder({
        key: existingPreset.key,
        label: existingPreset.label,
        description: existingPreset.description || '',
        icon: existingPreset.icon || '✨',
        flux_prefix: existingPreset.flux_prefix || '',
        negative_prompt: existingPreset.negative_prompt || '',
        style_guide_hint: existingPreset.style_guide_hint || '',
        themer_medium: existingPreset.themer_medium || '"digital painting," or "illustration,"',
        themer_quality: existingPreset.themer_quality || '"vivid colors, detailed"',
        loras: (existingPreset.loras || []).map(l => ({
          filename: l.filename || '', trigger: l.trigger || '',
          model_strength: l.model_strength ?? 0.7,
          clip_strength: l.clip_strength ?? 0.7,
          label: l.label || '',
        })),
      })
    } else {
      setEditingKey(null)
      setBuilder(emptyBuilder())
    }
    setBuilderError('')
    setShowBuilder(true)
  }

  async function saveCustomStyle() {
    if (!builder.key.trim()) { setBuilderError('Key is required (e.g. "my_ink_style")'); return }
    if (!builder.label.trim()) { setBuilderError('Label is required'); return }
    setBuilderSaving(true)
    setBuilderError('')
    try {
      const lorasPayload = builder.loras
        .filter(l => l.filename)
        .map(l => ({
          fragments: [l.filename.replace('.safetensors', '').replace('.pt', '')],
          trigger: l.trigger || '',
          model_strength: parseFloat(l.model_strength) || 0.7,
          clip_strength: parseFloat(l.clip_strength) || 0.7,
          dark_only: false,
          label: l.label || l.filename,
          download_url: null,
          download_note: '',
        }))
      const res = await fetch('/api/art-styles/custom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...builder, loras: lorasPayload }),
      })
      const json = await res.json()
      if (!res.ok) { setBuilderError(json.detail || 'Save failed'); return }
      setShowBuilder(false)
      refreshStyles()
      onArtStyleChange(builder.key.trim().replace(/ /g, '_'))
    } catch (e) {
      setBuilderError(String(e))
    } finally {
      setBuilderSaving(false)
    }
  }

  async function deleteCustomStyle(key) {
    if (!confirm(`Delete custom style "${key}"?`)) return
    await fetch(`/api/art-styles/custom/${key}`, { method: 'DELETE' })
    refreshStyles()
    if (artStyle === key) onArtStyleChange('mtg_fantasy')
  }

  async function saveCcDir() {
    setCcSaving(true); setCcMsg('')
    try {
      const res = await fetch('/api/frame-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cc_dir: ccDir }),
      })
      const j = await res.json()
      if (!j.ok) { setCcMsg(j.error || 'Could not save.'); return }
      // Re-check availability so the M15 / Full-art buttons unlock immediately
      const fs = await fetch('/api/frame-styles').then(r => r.ok ? r.json() : null)
      if (fs) setFrameStyles(fs.styles || [])
      setCcMsg(j.valid ? '✓ Card Conjurer detected — M15 frames unlocked.'
                       : (j.note || 'Saved, but no img/frames found at that path.'))
    } catch (e) {
      setCcMsg(String(e))
    } finally {
      setCcSaving(false)
    }
  }

  // Probe checkpoint availability, LoRA presets, and LLM catalog on mount.
  useEffect(() => {
    let cancelled = false
    // ComfyUI online/offline status
    fetch('/api/face-method').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setComfyOffline(!!d.comfyui_offline)
    }).catch(() => {})
    fetch('/api/art-styles').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setStylePresets(d)
    }).catch(() => {})
    fetch('/api/llm-models').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setLlmModels(d)
    }).catch(() => {})
    fetch('/api/frame-styles').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setFrameStyles(d.styles || [])
    }).catch(() => {})
    fetch('/api/frame-config').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setCcDir(d.cc_dir || '')
      setCcFromEnv(!!d.from_env)
    }).catch(() => {})
    fetch('/api/checkpoints').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      const ckpts = Array.isArray(d) ? d : (d.checkpoints || [])
      setCheckpoints(ckpts)
      // Derive model availability — note: SDXL type must NOT count as SD 3.5
      const hasDev_    = ckpts.some(c => (c.type||'').toUpperCase() === 'FLUX' && !c.filename.toLowerCase().includes('schnell'))
      const hasSchnell_= ckpts.some(c => c.filename.toLowerCase().includes('schnell'))
      const hasSDXL_   = ckpts.some(c => (c.type||'').toUpperCase().includes('SDXL'))
      const hasSd35_   = ckpts.some(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') })
      setHasDev(hasDev_); setHasSchnell(hasSchnell_); setHasSDXL(hasSDXL_); setHasSd35(hasSd35_)
      // Auto-correct stale model_speed if that checkpoint type disappeared
      if (modelSpeed === 'quality' && !hasDev_ && hasSchnell_) onModelSpeedChange('fast')
      else if (modelSpeed === 'fast' && !hasSchnell_ && hasDev_) onModelSpeedChange('quality')
      else if (modelSpeed === 'turbo' && !hasDev_) onModelSpeedChange(hasSchnell_ ? 'fast' : 'quality')
      else if (modelSpeed === 'sd35' && !hasSd35_) onModelSpeedChange(hasDev_ ? 'quality' : 'fast')
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  // ── Reflect a pinned "<Class> class" prefix on the chips when a deck is
  // loaded for editing (the appearance text persists, so re-highlight the chip).
  useEffect(() => {
    const m = (commanderPrompt || '').match(/^\s*([A-Za-z ]+?)\s+class\b/i)
    if (!m) return
    const name = m[1].trim().toLowerCase()
    const found = RO_JOB_CLASSES.flatMap(g => g.classes).find(c => c.toLowerCase() === name)
    if (found && found !== roJobClass) setRoJobClass(found)
  }, [])   // mount only — don't fight live typing

  // ── RO mode: auto-enable art gen + SDXL when ragnarok_online is selected ──
  useEffect(() => {
    if (!isRO) return
    if (!generateArt) onGenerateArtChange(true)
    if (checkpoints.length) {
      const sdxlCkpt = checkpoints.find(c => (c.type || '').toUpperCase().includes('SDXL'))
      if (sdxlCkpt && checkpoint !== sdxlCkpt.filename) onCheckpointChange(sdxlCkpt.filename)
    }
  }, [isRO, checkpoints])

  // ── Auto-select checkpoint when art style requires a specific model type ──
  useEffect(() => {
    if (!generateArt || !stylePresets.length || !checkpoints.length) return
    const preset = stylePresets.find(s => s.key === artStyle)
    if (!preset?.required_checkpoint_type) return
    const required = preset.required_checkpoint_type.toUpperCase()
    // Check if current checkpoint already satisfies the requirement
    const currentCkpt = checkpoints.find(c => c.filename === checkpoint)
    const currentType = (currentCkpt?.type || '').toUpperCase()
    if (currentType.includes(required) || currentType === required) return
    // Auto-select first matching checkpoint
    const match = checkpoints.find(c => (c.type || '').toUpperCase().includes(required))
    if (match && onCheckpointChange) onCheckpointChange(match.filename)
  }, [artStyle, stylePresets, checkpoints, generateArt])

  // ── Sync model_speed when an explicit checkpoint is chosen ───────────────
  useEffect(() => {
    if (!checkpoint || !checkpoints.length) return
    const ckpt = checkpoints.find(c => c.filename === checkpoint)
    if (!ckpt) return
    const t = (ckpt.type || '').toUpperCase()
    if (t.includes('FLUX')) {
      const isSchnell = ckpt.filename.toLowerCase().includes('schnell')
      if (isSchnell && modelSpeed !== 'fast') onModelSpeedChange('fast')
      // 'turbo' is also a dev mode — don't clobber it back to 'quality'.
      else if (!isSchnell && modelSpeed !== 'quality' && modelSpeed !== 'turbo') onModelSpeedChange('quality')
    } else if (t.includes('SD') && !t.includes('SDXL')) {
      if (modelSpeed !== 'sd35') onModelSpeedChange('sd35')
    }
    // SDXL: model_speed irrelevant when checkpoint is explicit — leave as-is
  }, [checkpoint, checkpoints])

  // ── RO job class picker handler ────────────────────────────────────────────
  function pickRoJobClass(cls) {
    const newClass = roJobClass === cls ? '' : cls
    setRoJobClass(newClass)
    // Remove any previously pinned class from the prompt, then prepend the new one
    let base = commanderPrompt
    if (roJobClass) {
      const escaped = roJobClass.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      base = base.replace(new RegExp(`\\s*,?\\s*${escaped}\\s*(class|job)?\\s*,?`, 'i'), '').trim().replace(/^,\s*/, '').replace(/,\s*$/, '')
    }
    if (newClass) {
      onCommanderPromptChange(base ? `${newClass} class, ${base}` : `${newClass} class`)
    } else {
      onCommanderPromptChange(base)
    }
  }

  async function handleNext() {
    setLoading(true)
    try { await onNext() } catch { setLoading(false) }
  }

  const canProceed = theme.trim().length > 3

  return (
    <div style={s.wrap}>
      {/* Commander chip */}
      <div style={s.commanderBar}>
        {commander.image_url
          ? <img src={commander.image_url} alt={commander.name} style={s.cmdImg} />
          : <div style={{ ...s.cmdImg, background: '#292524', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57534e' }}>?</div>
        }
        <div>
          <div style={s.cmdName}>{commander.name} <ManaCost cost={commander.mana_cost} size={15} /></div>
          <div style={s.cmdSub}>{commander.type_line}</div>
        </div>
      </div>

      <div style={s.card}>
        <h2 style={s.title}>Theme & Creature Types</h2>
        <p style={s.sub}>Set the world theme, then optionally reskin the deck's creature types — each replacement becomes the basis for that card's art.</p>

        {/* ── Creature-type replacements (from the generated decklist) ── */}
        {tribes.length > 0 && (
          <div style={s.section}>
            <label style={s.label}>Creature type replacements <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span></label>
            <div style={{ fontSize: 12, color: '#57534e', marginBottom: 10, lineHeight: 1.5 }}>
              These are the creature types in your generated deck. Type a replacement to reskin every creature of that type into the theme (e.g. <em>Goblin → Chrome Gremlin</em>) — in its name, art, and card type. Leave blank to keep a type as-is.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 8 }}>
              {tribes.map(t => (
                <div key={t.type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ flex: '0 0 96px', fontSize: 13, color: '#d6d3d1', textAlign: 'right' }}>
                    {t.type} <span style={{ color: '#57534e', fontSize: 11 }}>×{t.count}</span>
                  </div>
                  <span style={{ color: '#57534e' }}>→</span>
                  <input
                    type="text"
                    style={{
                      flex: 1, minWidth: 0, background: '#0c0a09', border: `1px solid ${(tribalOverrides[t.type] || '').trim() ? '#ca8a04' : '#44403c'}`,
                      borderRadius: 8, padding: '7px 10px', color: '#f5f5f4', fontSize: 13,
                      outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
                    }}
                    placeholder="keep as-is"
                    value={tribalOverrides[t.type] || ''}
                    onChange={e => setTribe(t.type, e.target.value)}
                    maxLength={40}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Divider */}
        <div style={{ height: 1, background: '#292524', marginBottom: 20 }} />

        {/* ── RO info banner ── */}
        {isRO && (
          <div style={{
            display: 'flex', gap: 12, padding: '12px 16px', marginBottom: 20,
            background: '#0a0c14', border: '1px solid #3730a344', borderRadius: 12,
            borderLeft: '3px solid #818cf8',
          }}>
            <span style={{ fontSize: 22, flexShrink: 0 }}>⚔️</span>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#818cf8', marginBottom: 4 }}>
                Ragnarok Online Mode
              </div>
              <div style={{ fontSize: 11, color: '#57534e', lineHeight: 1.6 }}>
                Illustrious XL + RO LoRA active. Art prompts automatically receive element tokens from mana color identity, race/class tags, and composition suffixes tuned to the training data. Pick a world location below and optionally pin a job class for your commander.
              </div>
            </div>
          </div>
        )}

        {/* ── Deck Vision (structured intake → tighter art brief) ── */}
        <div style={s.section}>
          <label style={s.label}>Deck Vision</label>
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 10 }}>
            Describe the world, then pin the genre, mood, and lighting. These compose into a focused brief for the art engine — far sharper than a one-line description. Per-card colors still follow each card's MTG mana identity; lighting here sets the overall atmosphere.
          </div>

          {/* Setting */}
          <div style={{ fontSize: 12, fontWeight: 700, color: '#d6d3d1', marginBottom: 6 }}>Setting <span style={{ color: '#57534e', fontWeight: 400 }}>— the world / place</span></div>
          <textarea
            style={s.textarea}
            placeholder={isRO
              ? 'e.g. Prontera castle grounds, golden spires, holy light streaming through stained glass'
              : 'e.g. a rain-slick neon megacity built into a canyon of derelict skyscrapers'}
            value={theme}
            onChange={e => onThemeChange(e.target.value)}
            rows={2}
          />
          <div style={s.exGrid}>
            {(isRO ? RO_THEMES : EXAMPLES).map(ex => (
              <button key={ex} style={s.exBtn} onClick={() => onThemeChange(ex)}>{ex}</button>
            ))}
          </div>

          {/* Genre / Mood / Lighting chip groups */}
          {[['Genre', VISION_GENRES, visionGenres, onVisionGenresChange],
            ['Mood', VISION_MOODS, visionMoods, onVisionMoodsChange],
            ['Lighting & palette', VISION_LIGHTING, visionLighting, onVisionLightingChange]].map(([label, opts, sel, on]) => (
            <div key={label} style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#d6d3d1', marginBottom: 6 }}>{label} <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span></div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {opts.map(o => (
                  <button key={o} style={vchip(sel.includes(o))} onClick={() => toggleArr(sel, o, on)}>{o}</button>
                ))}
              </div>
            </div>
          ))}

          {/* Inspirations */}
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#d6d3d1', marginBottom: 6 }}>Inspirations <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span></div>
            <input
              type="text"
              style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10, padding: '9px 14px', color: '#f5f5f4', fontSize: 14, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
              placeholder="e.g. Blade Runner, Studio Ghibli, Dark Souls"
              value={visionInspiration}
              onChange={e => onVisionInspirationChange && onVisionInspirationChange(e.target.value)}
              maxLength={120}
            />
          </div>

          {/* Live composed brief */}
          {visionBrief && (
            <div style={{ marginTop: 12, padding: 10, background: '#0c0a09', border: '1px solid #292524', borderRadius: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#78716c', marginBottom: 4 }}>🎨 Art brief sent to the engine</div>
              <div style={{ fontSize: 12, color: '#a8a29e', lineHeight: 1.5, fontStyle: 'italic' }}>{visionBrief}</div>
            </div>
          )}
        </div>

        {/* ── Commander character prompt ── */}
        <div style={s.section}>
          <label style={s.label}>
            Commander Appearance <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span>
          </label>
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8 }}>
            Describe <strong style={{ color: '#a8a29e' }}>{commander.name}</strong> specifically — their look, outfit, and distinguishing features like <strong style={{ color: '#a8a29e' }}>tattoos, scars, or piercings</strong>. Face matching only carries the <em>face</em>, so describe body details here (e.g. "sleeve tattoo of vines on the left arm"). This drives the commander's art and is layered on top of the world theme.
          </div>
          <textarea
            style={{ ...s.textarea, minHeight: 64 }}
            placeholder={isRO
              ? `e.g. Lord Knight in full plate armor, red cape, two-handed sword, heroic stance`
              : `e.g. scarred warrior in obsidian plate armor with crimson cape and glowing rune tattoos`
            }
            value={commanderPrompt}
            onChange={e => onCommanderPromptChange(e.target.value)}
            rows={2}
          />
        </div>

        {/* ── Crew appearance (only when crew photos were uploaded) ── */}
        {crewKey && onCrewPromptChange && (
          <div style={s.section}>
            <label style={s.label}>
              Crew Appearance <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span>
            </label>
            <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8 }}>
              Shared appearance notes applied to <strong style={{ color: '#a8a29e' }}>every creature card that uses a crew photo</strong>. Face matching only carries the face, so describe body details here — <strong style={{ color: '#a8a29e' }}>tattoos, scars, piercings, build, signature outfit</strong> (e.g. "muscular, full arm tattoos, leather jacket"). One description covers all crew, so keep it to traits they share.
            </div>
            <textarea
              style={{ ...s.textarea, minHeight: 56 }}
              placeholder="e.g. athletic build, sleeve tattoos, weathered leather armor"
              value={crewPrompt || ''}
              onChange={e => onCrewPromptChange(e.target.value)}
              rows={2}
            />
          </div>
        )}

        {/* ── RO Job Class Picker ── */}
        {isRO && (
          <div style={{ marginBottom: 24 }}>
            <label style={s.label}>
              Job Class <span style={{ color: '#57534e', fontWeight: 400 }}>(optional — pins a class to commander art)</span>
            </label>
            <div style={{ fontSize: 12, color: '#57534e', marginBottom: 10 }}>
              Pin a class to <strong style={{ color: '#a8a29e' }}>override</strong> your commander's auto-detected class (otherwise it's inferred from the card's creature type — e.g. a Knight defaults to Lord Knight). The class is emphasis-weighted in the art prompt so it renders reliably.
            </div>
            {RO_JOB_CLASSES.map(({ group, color, classes }) => (
              <div key={group} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 5 }}>
                  {group}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {classes.map(cls => {
                    const active = roJobClass === cls
                    return (
                      <button
                        key={cls}
                        onClick={() => pickRoJobClass(cls)}
                        style={{
                          fontSize: 11, padding: '4px 10px',
                          background: active ? `${color}22` : '#0c0a09',
                          border: `1px solid ${active ? color : '#44403c'}`,
                          borderRadius: 20, color: active ? color : '#78716c',
                          cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.12s',
                        }}
                      >
                        {cls}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
            {roJobClass && (
              <button
                onClick={() => pickRoJobClass(roJobClass)}
                style={{ marginTop: 4, fontSize: 11, color: '#57534e', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              >
                ✕ Clear job class
              </button>
            )}
          </div>
        )}

        {/* ── Your Name (commander first-name replacement) ── */}
        <div style={s.section}>
          <label style={s.label}>
            Your Name <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span>
          </label>
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8 }}>
            Replaces the AI-generated first name of your commander. For example, entering <em style={{ color: '#a8a29e' }}>Dorian</em> turns <em style={{ color: '#78716c' }}>Vex Thornwood, Hero of the Void</em> into <em style={{ color: '#a8a29e' }}>Dorian, Hero of the Void</em>.
          </div>
          <input
            type="text"
            style={{
              width: '100%', background: '#0c0a09', border: '1px solid #44403c',
              borderRadius: 10, padding: '10px 16px', color: '#f5f5f4', fontSize: 14,
              outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
            }}
            placeholder="e.g. Dorian, Lyra, Azrael…"
            value={userName || ''}
            onChange={e => onUserNameChange(e.target.value)}
            maxLength={40}
          />
        </div>

        {/* ── Set emblem prompt ── */}
        <div style={s.section}>
          <label style={s.label}>
            Set Emblem <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span>
          </label>
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8 }}>
            Describe the shape and color of the deck's set symbol. Keywords like <em style={{ color: '#a8a29e' }}>crown</em>, <em style={{ color: '#a8a29e' }}>star</em>, <em style={{ color: '#a8a29e' }}>shield</em>, <em style={{ color: '#a8a29e' }}>rune</em>, <em style={{ color: '#a8a29e' }}>diamond</em>, and colors like <em style={{ color: '#a8a29e' }}>gold</em>, <em style={{ color: '#a8a29e' }}>crimson</em>, <em style={{ color: '#a8a29e' }}>arcane purple</em>, <em style={{ color: '#a8a29e' }}>rainbow</em> are recognised. Leave blank for a theme-derived symbol.
          </div>
          <textarea
            style={{ ...s.textarea, minHeight: 48 }}
            placeholder="e.g. golden crown with rubies"
            value={emblemPrompt}
            onChange={e => onEmblemPromptChange(e.target.value)}
            rows={1}
          />
          <p style={s.exLabel}>Examples (click to use)</p>
          <div style={s.exGrid}>
            {EMBLEM_EXAMPLES.map(ex => (
              <button key={ex} style={s.exBtn} onClick={() => onEmblemPromptChange(ex)}>{ex}</button>
            ))}
          </div>

          {/* ── Custom mana pips ── */}
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginTop: 14, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={!!customPips}
              onChange={e => onCustomPipsChange(e.target.checked)}
              style={{ marginTop: 3, width: 16, height: 16, accentColor: '#d97706', cursor: 'pointer' }}
            />
            <span>
              <span style={{ fontSize: 14, color: '#f5f5f4', fontWeight: 600 }}>Custom themed mana pips</span>
              <span style={{ display: 'block', fontSize: 12, color: '#57534e', marginTop: 2, lineHeight: 1.5 }}>
                Replace the stock W/U/B/R/G mana symbols with themed pips — each a mana-coloured disc
                under one shared <em style={{ color: '#a8a29e' }}>black silhouette</em> of your deck's icon
                (taken from the Set Emblem above, or the theme). Best with a simple, iconic subject like
                a <em style={{ color: '#a8a29e' }}>cat</em>, <em style={{ color: '#a8a29e' }}>skull</em>, or
                <em style={{ color: '#a8a29e' }}> sword</em>. Generated with FLUX when ComfyUI is running,
                otherwise a clean vector fallback.
              </span>
            </span>
          </label>
        </div>

        {/* ── Card Border Theme ── */}
        <div style={s.section}>
          <label style={s.label}>
            Card Border Theme <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span>
          </label>
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8, lineHeight: 1.5 }}>
            Adds <strong style={{ color: '#a8a29e' }}>sparse corner decorations</strong> to every card's border and text box — subtle enough to never obscure text or art. Describe a style in a few words: the engine auto-detects vine, frost, flame, arcane, circuit, wave, shadow, and ornate motifs.
          </div>
          <input
            type="text"
            style={{
              width: '100%', background: '#0c0a09', border: '1px solid #44403c',
              borderRadius: 10, padding: '10px 16px', color: '#f5f5f4', fontSize: 14,
              outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
            }}
            placeholder="e.g. ancient stone runes, icy frost crystals, fire and embers…"
            value={borderTheme || ''}
            onChange={e => onBorderThemeChange(e.target.value)}
            maxLength={80}
          />
          {/* Style preview chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
            {(isRO ? RO_BORDER_PRESETS : [
              { label: '🌿 Vine',    kw: 'flowering vines and leaves',  col: '#4ade80' },
              { label: '❄ Frost',   kw: 'icy crystalline frost',        col: '#7dd3fc' },
              { label: '🔥 Flame',  kw: 'fire and ember sparks',        col: '#fb923c' },
              { label: '✦ Arcane', kw: 'glowing arcane sigils',         col: '#c084fc' },
              { label: '⚡ Circuit',kw: 'cyberpunk circuit traces',      col: '#22d3ee' },
              { label: '🌊 Wave',   kw: 'ocean waves and droplets',      col: '#38bdf8' },
              { label: '🌑 Shadow', kw: 'dark shadow wisps',             col: '#a78bfa' },
              { label: '🏅 Ornate', kw: 'golden baroque scrollwork',     col: '#fbbf24' },
            ]).map(({ label, kw, col }) => (
              <button
                key={kw}
                onClick={() => onBorderThemeChange(borderTheme === kw ? '' : kw)}
                style={{
                  fontSize: 11, padding: '4px 10px',
                  background: borderTheme === kw ? `${col}22` : '#0c0a09',
                  border: `1px solid ${borderTheme === kw ? col : '#44403c'}`,
                  borderRadius: 20, color: borderTheme === kw ? col : '#78716c',
                  cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.15s',
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {borderTheme && (
            <button
              onClick={() => onBorderThemeChange('')}
              style={{ marginTop: 8, fontSize: 11, color: '#57534e', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            >
              ✕ Clear border theme
            </button>
          )}
        </div>

        {/* ── Card Frame Style ── */}
        {onFrameStyleChange && (
          <div style={{ marginBottom: 20 }}>
            <label style={s.label}>Card Frame Style</label>
            <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8, lineHeight: 1.5 }}>
              Which frame artwork cards are rendered with. <strong style={{ color: '#a8a29e' }}>Built-in</strong> always works;{' '}
              <strong style={{ color: '#a8a29e' }}>Official-style (M15)</strong> renders from your own local Card Conjurer install.
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {(frameStyles.length ? frameStyles : [{ key: 'builtin', label: 'Built-in Frames', available: true, note: '' }]).map(fs => {
                const active   = (frameStyle || 'builtin') === fs.key
                const disabled = !fs.available
                return (
                  <button
                    key={fs.key}
                    onClick={() => !disabled && onFrameStyleChange(fs.key)}
                    disabled={disabled}
                    title={fs.note || ''}
                    style={{
                      fontSize: 12, padding: '8px 14px',
                      background: active ? '#1c2e1c' : '#0c0a09',
                      border: `1px solid ${active ? '#4ade80' : (disabled ? '#292524' : '#44403c')}`,
                      borderRadius: 10, color: disabled ? '#52525b' : (active ? '#4ade80' : '#a8a29e'),
                      cursor: disabled ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
                      transition: 'all 0.15s',
                    }}
                  >
                    {active ? '✓ ' : ''}{fs.label}{disabled ? ' 🔒' : ''}
                  </button>
                )
              })}
            </div>
            {/* Card Conjurer folder config — shown when an M15 style is locked
                OR a path is already configured (so users can edit it). */}
            {(frameStyles.some(fs => (fs.key === 'm15' || fs.key === 'm15_fullart') && !fs.available) || ccDir) && (
              <div style={{ marginTop: 10, padding: 10, background: '#0c0a09', border: '1px solid #292524', borderRadius: 10 }}>
                <div style={{ fontSize: 11, color: '#a8a29e', marginBottom: 6, lineHeight: 1.5 }}>
                  🗂 <strong>Card Conjurer folder</strong> — to unlock the M15 / Full-art frames, install Card Conjurer locally and point Myth Forge at its folder (the one containing <code>img/frames</code>).
                </div>
                {ccFromEnv ? (
                  <div style={{ fontSize: 11, color: '#57534e' }}>
                    Set via the <code>MYTHFORGE_CC_DIR</code> environment variable: <span style={{ color: '#78716c' }}>{ccDir}</span>
                  </div>
                ) : (
                  <>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input
                        type="text"
                        style={{
                          flex: 1, background: '#1c1917', border: '1px solid #44403c',
                          borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 13,
                          outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
                        }}
                        placeholder="C:\\path\\to\\cardconjurer"
                        value={ccDir}
                        onChange={e => setCcDir(e.target.value)}
                      />
                      <button
                        onClick={saveCcDir}
                        disabled={ccSaving}
                        style={{
                          fontSize: 12, padding: '8px 16px', background: '#1c2e1c',
                          border: '1px solid #4ade80', borderRadius: 8,
                          color: '#4ade80', cursor: ccSaving ? 'wait' : 'pointer', fontFamily: 'inherit',
                        }}
                      >
                        {ccSaving ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                    {ccMsg && (
                      <div style={{ fontSize: 11, color: ccMsg.startsWith('✓') ? '#4ade80' : '#d97706', marginTop: 6 }}>
                        {ccMsg}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* Commander tribe (optional reskin target) */}
        {onCommanderTribeChange && (
          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 700, color: '#d6d3d1', marginBottom: 4 }}>
              Commander creature type <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span>
            </label>
            <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8, lineHeight: 1.5 }}>
              The single tribe to <strong style={{ color: '#a8a29e' }}>reskin into the theme</strong> (e.g. <em>Cat → cyber bird</em>) — applied consistently to every card of that type. Leave blank to auto-detect from your commander. Other creature types keep their own kind and are drawn as themselves.
            </div>
            <input
              type="text"
              style={{
                width: '100%', background: '#0c0a09', border: '1px solid #44403c',
                borderRadius: 10, padding: '10px 16px', color: '#f5f5f4', fontSize: 14,
                outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
              }}
              placeholder="e.g. Faerie, Cat, Goblin… (blank = auto)"
              value={commanderTribe || ''}
              onChange={e => onCommanderTribeChange(e.target.value)}
              maxLength={40}
            />
          </div>
        )}

        {/* Divider */}
        <div style={{ height: 1, background: '#292524', marginBottom: 20 }} />

        {/* Face reference badge (if user uploaded photos) */}
        {faceKey && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#0a0800', border: '1px solid #eab30833', borderRadius: 10, marginBottom: 16 }}>
            <span style={{ fontSize: 18 }}>👤</span>
            <div>
              <div style={{ fontSize: 13, color: '#eab308', fontWeight: 700 }}>Face reference active</div>
              <div style={{ fontSize: 11, color: '#78716c' }}>{faceMethod || 'Face photos uploaded'} · Humanoid card art will resemble your photos</div>
            </div>
          </div>
        )}

        {/* ComfyUI art toggle */}
        <div style={s.artRow}>
          <button
            style={{ ...s.toggle, background: generateArt ? '#ca8a04' : '#44403c' }}
            onClick={() => onGenerateArtChange(!generateArt)}
          >
            <div style={{ ...s.toggleThumb, left: generateArt ? 18 : 2 }} />
          </button>
          <div style={{ flex: 1 }}>
            <div style={s.toggleLabel}>
              {isRO ? 'Generate card art with ComfyUI (Illustrious XL + RO LoRA)' : 'Generate card art with ComfyUI FLUX'}
            </div>
            <div style={s.toggleSlow}>
              {generateArt && !comfyOffline
                ? isRO
                  ? (hasSDXL ? '✓ Illustrious XL detected — RO LoRA ready' : '⚠ No SDXL checkpoint found — RO LoRA requires Illustrious XL')
                  : (hasDev && hasSchnell ? 'Dev & Schnell detected' : hasDev ? 'FLUX Dev detected' : hasSchnell ? 'FLUX Schnell detected' : 'Checkpoint detected')
                : generateArt && comfyOffline
                  ? '⚠ ComfyUI not running — start it before building'
                  : isRO
                    ? 'Requires local ComfyUI + Illustrious XL checkpoint.'
                    : 'Requires local ComfyUI + FLUX checkpoint.'}
            </div>
          </div>
        </div>

        {/* ── Art style / LoRA preset selector ── */}
        {generateArt && stylePresets.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <label style={{ ...s.label, marginBottom: 0 }}>Art Style</label>
              <button
                onClick={() => openBuilder()}
                style={{
                  padding: '5px 12px', background: '#0c0a09', border: '1px solid #44403c',
                  borderRadius: 8, color: '#a8a29e', cursor: 'pointer', fontSize: 12,
                  fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 5,
                }}
              >
                <span>⚙️</span> Build Custom Style
              </button>
            </div>
            <div style={{ fontSize: 12, color: '#57534e', marginBottom: 10 }}>
              Each style uses a different LoRA stack. <span style={{ color: '#78716c' }}>✓ Ready</span> means all LoRAs are installed. Missing LoRAs click for download links — style still works prompt-only without them.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
              {stylePresets.map(st => {
                const isSelected = artStyle === st.key
                const isCustom = !!st.custom
                const statusColor = st.ready ? '#4ade80' : st.partial ? '#eab308' : '#78716c'
                const statusLabel = st.ready ? '✓ Ready' : st.partial ? '~ Partial' : '○ Prompt-only'
                const reqType = (st.required_checkpoint_type || '').toUpperCase()
                const reqColor = reqType.includes('SDXL') ? '#a78bfa' : reqType.includes('FLUX') ? '#22d3ee' : reqType.includes('SD') ? '#818cf8' : null
                return (
                  <div key={st.key} style={{ position: 'relative' }}>
                    <button
                      onClick={() => onArtStyleChange(st.key)}
                      style={{
                        width: '100%', padding: '10px 10px 8px', borderRadius: 10,
                        background: isSelected ? (isCustom ? '#0a1018' : '#1a1208') : '#0c0a09',
                        border: `1px solid ${isSelected ? (isCustom ? '#38bdf8' : '#ca8a04') : (isCustom ? '#1e3a4a' : '#292524')}`,
                        textAlign: 'left', fontFamily: 'inherit', cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      <div style={{ fontSize: 18, marginBottom: 4 }}>{st.icon}</div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: isSelected ? (isCustom ? '#38bdf8' : '#eab308') : '#a8a29e', marginBottom: 2, lineHeight: 1.2 }}>
                        {st.label}{isCustom && <span style={{ fontSize: 9, color: '#38bdf8', marginLeft: 4 }}>CUSTOM</span>}
                      </div>
                      <div style={{ fontSize: 10, color: statusColor, marginBottom: reqColor ? 2 : 4 }}>
                        {statusLabel}
                      </div>
                      {reqColor && (
                        <div style={{ fontSize: 9, color: reqColor, fontWeight: 700, letterSpacing: '0.04em' }}>
                          {reqType} required
                        </div>
                      )}
                    </button>
                    {/* Edit button for custom styles */}
                    {isCustom && (
                      <button
                        onClick={() => openBuilder(st)}
                        style={{
                          position: 'absolute', top: 6, right: 22,
                          background: 'none', border: 'none', color: '#38bdf8',
                          cursor: 'pointer', fontSize: 11, padding: 2,
                        }}
                        title="Edit custom style"
                      >✏️</button>
                    )}
                    {isCustom && (
                      <button
                        onClick={() => deleteCustomStyle(st.key)}
                        style={{
                          position: 'absolute', top: 6, right: 4,
                          background: 'none', border: 'none', color: '#ef4444',
                          cursor: 'pointer', fontSize: 11, padding: 2,
                        }}
                        title="Delete custom style"
                      >✕</button>
                    )}
                    {/* Download hint toggle for non-ready built-in styles */}
                    {!st.ready && !isCustom && (
                      <button
                        onClick={() => setExpandedStyle(expandedStyle === st.key ? null : st.key)}
                        style={{
                          position: 'absolute', top: 6, right: 6,
                          background: 'none', border: 'none', color: '#57534e',
                          cursor: 'pointer', fontSize: 12, padding: 2,
                        }}
                        title="Show download links"
                      >
                        {expandedStyle === st.key ? '▲' : '▼'}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Selected style description */}
            {(() => {
              const st = stylePresets.find(s => s.key === artStyle)
              if (!st) return null
              return (
                <div style={{ marginTop: 8, fontSize: 12, color: '#57534e', lineHeight: 1.5 }}>
                  {st.description}
                </div>
              )
            })()}

            {/* Expanded download details for selected style */}
            {expandedStyle && (() => {
              const st = stylePresets.find(s => s.key === expandedStyle)
              if (!st) return null
              const missing = st.loras.filter(l => !l.installed)
              if (!missing.length) return null
              return (
                <div style={{ marginTop: 8, padding: '12px 14px', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10 }}>
                  <div style={{ fontSize: 12, color: '#a8a29e', fontWeight: 700, marginBottom: 8 }}>
                    Missing LoRAs for {st.label}:
                  </div>
                  {missing.map(l => (
                    <div key={l.label} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 12, color: '#78716c', marginBottom: 2 }}>
                        <span style={{ color: '#ef4444' }}>✗</span> {l.label}
                      </div>
                      {l.download_note && (
                        <div style={{ fontSize: 11, color: '#57534e', marginBottom: 2 }}>
                          {l.download_note}
                        </div>
                      )}
                      {l.download_url && (
                        <a
                          href={l.download_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ fontSize: 11, color: '#ca8a04', textDecoration: 'none' }}
                        >
                          ↗ {l.download_url.replace('https://', '')}
                        </a>
                      )}
                    </div>
                  ))}
                  <div style={{ fontSize: 11, color: '#57534e', marginTop: 4 }}>
                    Save to: C:\Users\rvn92\Documents\ComfyUI\models\loras\
                  </div>
                </div>
              )
            })()}
          </div>
        )}

        {/* ── Custom Style Builder Modal ── */}
        {showBuilder && (
          <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)',
            zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 16,
          }}>
            <div style={{
              background: '#1c1917', border: '1px solid #44403c', borderRadius: 16,
              padding: 24, width: '100%', maxWidth: 640, maxHeight: '90vh',
              overflowY: 'auto',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#eab308' }}>
                  ⚙️ {editingKey ? 'Edit Custom Style' : 'Build Custom Style'}
                </div>
                <button onClick={() => setShowBuilder(false)} style={{ background: 'none', border: 'none', color: '#78716c', cursor: 'pointer', fontSize: 18 }}>✕</button>
              </div>

              {/* Key + Label + Icon row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 72px', gap: 10, marginBottom: 14 }}>
                <div>
                  <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>Style Key (slug) *</label>
                  <input
                    style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
                    placeholder="my_ink_style"
                    value={builder.key}
                    onChange={e => setBuilder(b => ({ ...b, key: e.target.value.replace(/\s+/g,'_').toLowerCase() }))}
                    disabled={!!editingKey}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>Display Label *</label>
                  <input
                    style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
                    placeholder="My Ink Style"
                    value={builder.label}
                    onChange={e => setBuilder(b => ({ ...b, label: e.target.value }))}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>Icon</label>
                  <input
                    style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 18, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box', textAlign: 'center' }}
                    value={builder.icon}
                    onChange={e => setBuilder(b => ({ ...b, icon: e.target.value }))}
                    maxLength={4}
                  />
                </div>
              </div>

              {/* Description */}
              <div style={{ marginBottom: 14 }}>
                <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>Description</label>
                <input
                  style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
                  placeholder="Brief description shown in the style card"
                  value={builder.description}
                  onChange={e => setBuilder(b => ({ ...b, description: e.target.value }))}
                />
              </div>

              {/* FLUX prefix */}
              <div style={{ marginBottom: 14 }}>
                <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>
                  FLUX Prompt Prefix <span style={{ color: '#44403c' }}>(optional — overrides default)</span>
                </label>
                <textarea
                  style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 12, outline: 'none', fontFamily: 'inherit', minHeight: 72, resize: 'vertical', boxSizing: 'border-box' }}
                  placeholder="e.g. Ink wash illustration style, bold black lines, monochrome with selective color washes..."
                  value={builder.flux_prefix}
                  onChange={e => setBuilder(b => ({ ...b, flux_prefix: e.target.value }))}
                />
              </div>

              {/* Style guide hint */}
              <div style={{ marginBottom: 14 }}>
                <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>
                  Style Guide Hint <span style={{ color: '#44403c' }}>(tells LLM what art medium to use)</span>
                </label>
                <input
                  style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
                  placeholder="e.g. ink wash illustration, bold linework, selective watercolor"
                  value={builder.style_guide_hint}
                  onChange={e => setBuilder(b => ({ ...b, style_guide_hint: e.target.value }))}
                />
              </div>

              {/* Themer medium + quality */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
                <div>
                  <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>Themer Medium</label>
                  <input
                    style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 12, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
                    value={builder.themer_medium}
                    onChange={e => setBuilder(b => ({ ...b, themer_medium: e.target.value }))}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>Themer Quality</label>
                  <input
                    style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 12, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
                    value={builder.themer_quality}
                    onChange={e => setBuilder(b => ({ ...b, themer_quality: e.target.value }))}
                  />
                </div>
              </div>

              {/* Negative prompt */}
              <div style={{ marginBottom: 18 }}>
                <label style={{ fontSize: 11, color: '#78716c', display: 'block', marginBottom: 4 }}>
                  Negative Prompt <span style={{ color: '#44403c' }}>(optional — leave blank for default)</span>
                </label>
                <textarea
                  style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 8, padding: '8px 12px', color: '#f5f5f4', fontSize: 12, outline: 'none', fontFamily: 'inherit', minHeight: 56, resize: 'vertical', boxSizing: 'border-box' }}
                  placeholder="bad hands, extra fingers, watermark..."
                  value={builder.negative_prompt}
                  onChange={e => setBuilder(b => ({ ...b, negative_prompt: e.target.value }))}
                />
              </div>

              {/* LoRA stack */}
              <div style={{ marginBottom: 18 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <label style={{ fontSize: 11, color: '#78716c' }}>LoRA Stack</label>
                  <button
                    onClick={() => setBuilder(b => ({ ...b, loras: [...b.loras, { filename: '', trigger: '', model_strength: 0.7, clip_strength: 0.7, label: '' }] }))}
                    style={{ padding: '4px 10px', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 6, color: '#a8a29e', cursor: 'pointer', fontSize: 12, fontFamily: 'inherit' }}
                  >
                    + Add LoRA
                  </button>
                </div>
                {builder.loras.length === 0 && (
                  <div style={{ fontSize: 12, color: '#44403c', textAlign: 'center', padding: '16px 0', border: '1px dashed #292524', borderRadius: 8 }}>
                    No LoRAs added — style will use FLUX prompt-only
                  </div>
                )}
                {builder.loras.map((lora, i) => (
                  <div key={i} style={{ background: '#0c0a09', border: '1px solid #292524', borderRadius: 10, padding: 12, marginBottom: 8 }}>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                      <div style={{ flex: 2 }}>
                        <label style={{ fontSize: 10, color: '#57534e', display: 'block', marginBottom: 3 }}>Filename</label>
                        {installedLoras.length > 0 ? (
                          <select
                            style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 6, padding: '7px 8px', color: '#f5f5f4', fontSize: 12, fontFamily: 'inherit' }}
                            value={lora.filename}
                            onChange={e => setBuilder(b => ({ ...b, loras: b.loras.map((l,j) => j===i ? { ...l, filename: e.target.value, label: l.label || e.target.value.replace('.safetensors','') } : l) }))}
                          >
                            <option value="">— pick a LoRA —</option>
                            {installedLoras.map(f => <option key={f} value={f}>{f}</option>)}
                          </select>
                        ) : (
                          <input
                            style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 6, padding: '7px 8px', color: '#f5f5f4', fontSize: 12, fontFamily: 'inherit', boxSizing: 'border-box' }}
                            placeholder="filename.safetensors"
                            value={lora.filename}
                            onChange={e => setBuilder(b => ({ ...b, loras: b.loras.map((l,j) => j===i ? { ...l, filename: e.target.value } : l) }))}
                          />
                        )}
                      </div>
                      <div style={{ flex: 2 }}>
                        <label style={{ fontSize: 10, color: '#57534e', display: 'block', marginBottom: 3 }}>Trigger Word(s)</label>
                        <input
                          style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 6, padding: '7px 8px', color: '#f5f5f4', fontSize: 12, fontFamily: 'inherit', boxSizing: 'border-box' }}
                          placeholder="trigger word or blank"
                          value={lora.trigger}
                          onChange={e => setBuilder(b => ({ ...b, loras: b.loras.map((l,j) => j===i ? { ...l, trigger: e.target.value } : l) }))}
                        />
                      </div>
                      <button
                        onClick={() => setBuilder(b => ({ ...b, loras: b.loras.filter((_,j) => j!==i) }))}
                        style={{ alignSelf: 'flex-end', padding: '7px 10px', background: 'none', border: '1px solid #44403c', borderRadius: 6, color: '#ef4444', cursor: 'pointer', fontSize: 13, marginBottom: 0 }}
                      >✕</button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                      <div>
                        <label style={{ fontSize: 10, color: '#57534e', display: 'block', marginBottom: 3 }}>Label</label>
                        <input
                          style={{ width: '100%', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 6, padding: '7px 8px', color: '#f5f5f4', fontSize: 12, fontFamily: 'inherit', boxSizing: 'border-box' }}
                          placeholder="My LoRA"
                          value={lora.label}
                          onChange={e => setBuilder(b => ({ ...b, loras: b.loras.map((l,j) => j===i ? { ...l, label: e.target.value } : l) }))}
                        />
                      </div>
                      <div>
                        <label style={{ fontSize: 10, color: '#57534e', display: 'block', marginBottom: 3 }}>Model Strength</label>
                        <input
                          type="range" min="0" max="1" step="0.05"
                          style={{ width: '100%', marginTop: 4 }}
                          value={lora.model_strength}
                          onChange={e => setBuilder(b => ({ ...b, loras: b.loras.map((l,j) => j===i ? { ...l, model_strength: parseFloat(e.target.value) } : l) }))}
                        />
                        <div style={{ fontSize: 10, color: '#78716c', textAlign: 'center' }}>{lora.model_strength}</div>
                      </div>
                      <div>
                        <label style={{ fontSize: 10, color: '#57534e', display: 'block', marginBottom: 3 }}>CLIP Strength</label>
                        <input
                          type="range" min="0" max="1" step="0.05"
                          style={{ width: '100%', marginTop: 4 }}
                          value={lora.clip_strength}
                          onChange={e => setBuilder(b => ({ ...b, loras: b.loras.map((l,j) => j===i ? { ...l, clip_strength: parseFloat(e.target.value) } : l) }))}
                        />
                        <div style={{ fontSize: 10, color: '#78716c', textAlign: 'center' }}>{lora.clip_strength}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {builderError && (
                <div style={{ padding: '8px 12px', background: '#1f0a0a', border: '1px solid #7f1d1d', borderRadius: 8, marginBottom: 14, fontSize: 12, color: '#fca5a5' }}>
                  {builderError}
                </div>
              )}

              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button onClick={() => setShowBuilder(false)} style={{ padding: '9px 20px', background: 'none', border: '1px solid #44403c', borderRadius: 9, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit' }}>
                  Cancel
                </button>
                <button
                  onClick={saveCustomStyle}
                  disabled={builderSaving}
                  style={{ padding: '9px 22px', background: 'linear-gradient(180deg,#0ea5e9,#0369a1)', border: 'none', borderRadius: 9, color: '#fff', fontWeight: 700, cursor: builderSaving ? 'wait' : 'pointer', fontFamily: 'inherit', opacity: builderSaving ? 0.6 : 1 }}
                >
                  {builderSaving ? 'Saving…' : editingKey ? 'Update Style' : 'Create Style'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Image model picker ── */}
        {generateArt && !comfyOffline && checkpoints.length > 0 && (() => {
          // Determine which button is currently active based on the selected checkpoint
          const isSchnellActive = checkpoint && checkpoint.toLowerCase().includes('schnell')
          const isDevCkpt       = checkpoint && activeCheckpointType.includes('FLUX') && !isSchnellActive
          const isTurboActive   = isDevCkpt && modelSpeed === 'turbo'
          const isDevActive     = isDevCkpt && modelSpeed !== 'turbo'
          const isSDXLActive    = activeCheckpointType.includes('SDXL')
          const isSd35Active    = activeCheckpointType.includes('SD') && !isSDXLActive

          // Turbo needs a distillation LoRA installed (keep fragments in sync with
          // image_gen._TURBO_LORA_FRAGMENTS).
          const TURBO_FRAGS = ['flux.1-turbo', 'flux-turbo', 'fluxturbo', 'hyper-flux', 'hyper-sd']
          const hasTurboLora = installedLoras.some(f =>
            TURBO_FRAGS.some(frag => String(f).toLowerCase().includes(frag)))

          const selectDev = () => {
            const c = checkpoints.find(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))
            if (c) { onCheckpointChange(c.filename); onModelSpeedChange('quality') }
          }
          const selectTurbo = () => {
            const c = checkpoints.find(c => (c.type||'').toUpperCase().includes('FLUX') && !c.filename.toLowerCase().includes('schnell'))
            if (c) { onCheckpointChange(c.filename); onModelSpeedChange('turbo') }
          }
          const selectSDXL = () => {
            const c = checkpoints.find(c => (c.type||'').toUpperCase().includes('SDXL'))
            if (c) { onCheckpointChange(c.filename) }
          }
          const selectSd35 = () => {
            const c = checkpoints.find(c => { const t=(c.type||'').toUpperCase(); return t.includes('SD') && !t.includes('SDXL') })
            if (c) { onCheckpointChange(c.filename); onModelSpeedChange('sd35') }
          }
          const selectSchnell = () => {
            const c = checkpoints.find(c => c.filename.toLowerCase().includes('schnell'))
            if (c) { onCheckpointChange(c.filename); onModelSpeedChange('fast') }
          }

          return (
            <div style={{ marginBottom: 20 }}>
              <label style={s.label}>Image Model</label>
              <div style={{ display: 'flex', gap: 8 }}>

                {/* FLUX Dev */}
                {hasDev && (
                  <button onClick={selectDev} style={{
                    flex: 1, padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
                    background: isDevActive ? '#1c1410' : '#0c0a09',
                    border: `1px solid ${isDevActive ? '#ca8a04' : '#292524'}`,
                    textAlign: 'left', fontFamily: 'inherit', transition: 'all 0.15s',
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: isDevActive ? '#eab308' : '#a8a29e', marginBottom: 3 }}>✦ Quality</div>
                    <div style={{ fontSize: 11, color: '#57534e' }}>FLUX Dev · ~30s/card</div>
                  </button>
                )}

                {/* FLUX Dev + Turbo LoRA (only when a turbo LoRA is installed) */}
                {hasDev && hasTurboLora && (
                  <button onClick={selectTurbo} style={{
                    flex: 1, padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
                    background: isTurboActive ? '#101c14' : '#0c0a09',
                    border: `1px solid ${isTurboActive ? '#22c55e' : '#292524'}`,
                    textAlign: 'left', fontFamily: 'inherit', transition: 'all 0.15s',
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: isTurboActive ? '#22c55e' : '#a8a29e', marginBottom: 3 }}>⚡ Turbo</div>
                    <div style={{ fontSize: 11, color: '#57534e' }}>FLUX Dev · ~8s/card · near-Quality</div>
                  </button>
                )}

                {/* Illustrious XL (SDXL) */}
                {hasSDXL && (
                  <button onClick={selectSDXL} style={{
                    flex: 1, padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
                    background: isSDXLActive ? '#120a1e' : '#0c0a09',
                    border: `1px solid ${isSDXLActive ? '#a78bfa' : '#292524'}`,
                    textAlign: 'left', fontFamily: 'inherit', transition: 'all 0.15s',
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: isSDXLActive ? '#a78bfa' : '#a8a29e', marginBottom: 3 }}>🎨 Illustrious XL</div>
                    <div style={{ fontSize: 11, color: '#57534e' }}>SDXL · ~20s/card · LoRA styles</div>
                  </button>
                )}

                {/* SD 3.5 */}
                {hasSd35 && (
                  <button onClick={selectSd35} style={{
                    flex: 1, padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
                    background: isSd35Active ? '#100a18' : '#0c0a09',
                    border: `1px solid ${isSd35Active ? '#818cf8' : '#292524'}`,
                    textAlign: 'left', fontFamily: 'inherit', transition: 'all 0.15s',
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: isSd35Active ? '#818cf8' : '#a8a29e', marginBottom: 3 }}>✧ SD 3.5</div>
                    <div style={{ fontSize: 11, color: '#57534e' }}>SD 3.5 Large · ~30s/card</div>
                  </button>
                )}

                {/* FLUX Schnell */}
                {hasSchnell && (
                  <button onClick={selectSchnell} style={{
                    flex: 1, padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
                    background: isSchnellActive ? '#0a1008' : '#0c0a09',
                    border: `1px solid ${isSchnellActive ? '#4ade80' : '#292524'}`,
                    textAlign: 'left', fontFamily: 'inherit', transition: 'all 0.15s',
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: isSchnellActive ? '#4ade80' : '#a8a29e', marginBottom: 3 }}>⚡ Fast</div>
                    <div style={{ fontSize: 11, color: '#57534e' }}>FLUX Schnell · ~6s/card</div>
                  </button>
                )}

              </div>
              {/* Show active checkpoint filename as fine print */}
              {checkpoint && (
                <div style={{ fontSize: 10, color: '#44403c', marginTop: 6, paddingLeft: 2 }}>
                  Using: {checkpoint}
                </div>
              )}
            </div>
          )
        })()}

        {/* ── LLM model selector ── */}
        {llmModels.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <label style={s.label}>Theming LLM</label>
            <div style={{ fontSize: 12, color: '#57534e', marginBottom: 10 }}>
              Picks the local LLM that generates card names, art prompts, and flavour text. Bigger models produce richer prose but take longer per batch.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 }}>
              {llmModels.map(m => {
                const isSelected = (llmModel || 'qwen3:14b') === m.key
                const tierColor  = m.tier === 'quality' ? '#a78bfa' : m.tier === 'fastest' ? '#4ade80' : '#eab308'
                return (
                  <button
                    key={m.key}
                    onClick={() => m.installed && onLlmModelChange && onLlmModelChange(m.key)}
                    disabled={!m.installed}
                    title={m.installed ? m.description : `Not installed — run: ollama pull ${m.key}`}
                    style={{
                      padding: '10px 12px', borderRadius: 10,
                      cursor: m.installed ? 'pointer' : 'not-allowed',
                      background: isSelected ? '#181522' : '#0c0a09',
                      border: `1px solid ${isSelected ? tierColor : '#292524'}`,
                      textAlign: 'left', fontFamily: 'inherit',
                      opacity: m.installed ? 1 : 0.45,
                    }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 700, color: isSelected ? tierColor : '#a8a29e', marginBottom: 3 }}>
                      {m.label}
                    </div>
                    <div style={{ fontSize: 10, color: '#57534e', marginBottom: 2 }}>
                      {m.size_gb} GB · {m.tier}
                    </div>
                    <div style={{ fontSize: 10, color: '#57534e', lineHeight: 1.4 }}>
                      {m.installed ? m.description.split('.')[0] : `Not installed — \`ollama pull ${m.key}\``}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {genSettings && <AdvancedPanel step="theme" settings={genSettings} />}

        <div style={s.footer}>
          <button style={s.btnBack} onClick={onBack} disabled={loading}>← Back</button>
          <button
            style={{ ...s.btnNext, ...((!canProceed || loading) ? s.btnNextDisabled : {}) }}
            onClick={handleNext}
            disabled={!canProceed || loading}
          >
            {loading ? 'Starting build...' : 'Build Deck →'}
          </button>
        </div>
      </div>
    </div>
  )
}
