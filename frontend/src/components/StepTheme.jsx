import { useEffect, useState } from 'react'
import ManaCost from './ManaCost'

const EXAMPLES = [
  'dark gothic necromancer city',
  'ancient deep sea leviathan realm',
  'steampunk goblin industrial revolution',
  'eldritch cosmic horror space void',
  'enchanted forest fae realm',
  'volcanic dragon empire',
]

const BRACKETS = [
  {
    n: 1, label: 'Exhibition',
    color: '#4ade80', bg: '#052e16',
    desc: 'Precon power level. No staples, no infinite combos. Fully theme-focused.',
    pills: ['No Game Changers', 'No Extra Turns', 'No Combos', 'Basics-heavy lands'],
  },
  {
    n: 2, label: 'Core',
    color: '#a3e635', bg: '#1a2e05',
    desc: 'Solid casual play. Good synergies but no format-warping powerhouses.',
    pills: ['No Game Changers', 'No Extra Turns', 'Check Lands OK', 'No Fast Mana'],
  },
  {
    n: 3, label: 'Upgraded',
    color: '#eab308', bg: '#422006',
    desc: 'The most popular bracket. Strong synergies, up to 3 Game Changers allowed.',
    pills: ['≤3 Game Changers', 'Extra Turns OK', 'Fetch/Shock Lands', 'No MLD'],
  },
  {
    n: 4, label: 'Optimized',
    color: '#f97316', bg: '#431407',
    desc: 'High-powered. Infinite combos, tutors, fast mana — bring your strongest cards.',
    pills: ['Unlimited Game Changers', 'Infinite Combos OK', 'MLD OK', 'All Lands'],
  },
  {
    n: 5, label: 'cEDH',
    color: '#ef4444', bg: '#450a0a',
    desc: 'Competitive Commander. Maximum power, fastest possible wins. No mercy.',
    pills: ['No Restrictions', 'Tutor Everything', 'Win ASAP', 'Best Cards Only'],
  },
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
  commanderPrompt, onCommanderPromptChange,
  userName, onUserNameChange,
  emblemPrompt, onEmblemPromptChange,
  borderTheme, onBorderThemeChange,
  artStyle, onArtStyleChange,
  bracket, onBracketChange,
  generateArt, onGenerateArtChange,
  modelSpeed, onModelSpeedChange,
  llmModel, onLlmModelChange,
  faceKey, faceMethod,
  onNext, onBack,
}) {
  const [loading, setLoading]           = useState(false)
  const [hasSchnell, setHasSchnell]     = useState(false)
  const [hasDev, setHasDev]             = useState(false)
  const [hasSd35, setHasSd35]           = useState(false)
  const [comfyOffline, setComfyOffline] = useState(false)
  const [stylePresets, setStylePresets] = useState([])
  const [expandedStyle, setExpandedStyle] = useState(null)
  const [llmModels, setLlmModels]       = useState([])
  const selected = BRACKETS.find(b => b.n === bracket) || BRACKETS[2]

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

  // Probe checkpoint availability, LoRA presets, and LLM catalog on mount.
  useEffect(() => {
    let cancelled = false
    fetch('/api/face-method').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setComfyOffline(!!d.comfyui_offline)
      setHasSchnell(!!d.has_schnell)
      setHasDev(!!d.has_dev)
      const schnellCkpts = d.checkpoints?.sd35 || []
      setHasSd35(schnellCkpts.length > 0)
      // Auto-correct stale model_speed selections if a checkpoint disappeared.
      if (modelSpeed === 'quality' && !d.has_dev && d.has_schnell) {
        onModelSpeedChange('fast')
      } else if (modelSpeed === 'fast' && !d.has_schnell && d.has_dev) {
        onModelSpeedChange('quality')
      } else if (modelSpeed === 'sd35' && schnellCkpts.length === 0) {
        onModelSpeedChange(d.has_dev ? 'quality' : (d.has_schnell ? 'fast' : 'quality'))
      }
    }).catch(() => {})
    fetch('/api/art-styles').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setStylePresets(d)
    }).catch(() => {})
    fetch('/api/llm-models').then(r => r.ok ? r.json() : null).then(d => {
      if (cancelled || !d) return
      setLlmModels(d)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

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
        <h2 style={s.title}>Power Level & Theme</h2>
        <p style={s.sub}>Set your bracket and art theme. The bracket controls which cards the deck builder is allowed to include.</p>

        {/* ── Bracket selector ── */}
        <div style={s.section}>
          <label style={s.label}>Bracket (EDH Power Level)</label>

          {/* 5-segment control */}
          <div style={{ display: 'flex', gap: 4, background: '#0c0a09', borderRadius: 10, padding: 4, marginBottom: 12 }}>
            {BRACKETS.map(b => (
              <button
                key={b.n}
                onClick={() => onBracketChange(b.n)}
                style={{
                  flex: 1, padding: '10px 4px', borderRadius: 7, border: 'none',
                  background: bracket === b.n ? b.color : 'transparent',
                  color: bracket === b.n ? '#0c0a09' : '#57534e',
                  fontWeight: bracket === b.n ? 800 : 500,
                  cursor: 'pointer', fontFamily: 'inherit', fontSize: 13,
                  transition: 'all 0.15s',
                }}
              >
                <div style={{ fontSize: 16, fontWeight: 800 }}>{b.n}</div>
                <div style={{ fontSize: 10, marginTop: 2, opacity: bracket === b.n ? 1 : 0.7 }}>{b.label}</div>
              </button>
            ))}
          </div>

          {/* Selected bracket detail card */}
          <div style={{
            background: selected.bg,
            border: `1px solid ${selected.color}44`,
            borderLeft: `3px solid ${selected.color}`,
            borderRadius: 8, padding: '12px 14px',
          }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: selected.color, marginBottom: 4 }}>
              Bracket {selected.n} — {selected.label}
            </div>
            <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 10, lineHeight: 1.5 }}>
              {selected.desc}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {selected.pills.map(pill => (
                <span key={pill} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 12,
                  background: `${selected.color}22`, color: selected.color,
                  border: `1px solid ${selected.color}44`,
                }}>
                  {pill}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: '#292524', marginBottom: 20 }} />

        {/* ── World & Palette theme ── */}
        <div style={s.section}>
          <label style={s.label}>World &amp; Color Theme</label>
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8 }}>
            Describe the setting, mood, and palette. Colors here blend with each card's MTG mana identity — a black card in a neon theme stays dark and electric, not pastel.
          </div>
          <textarea
            style={s.textarea}
            placeholder="e.g. dark gothic necromancer city with bone-white spires and sickly green fog"
            value={theme}
            onChange={e => onThemeChange(e.target.value)}
            rows={2}
          />
          <p style={s.exLabel}>Examples (click to use)</p>
          <div style={s.exGrid}>
            {EXAMPLES.map(ex => (
              <button key={ex} style={s.exBtn} onClick={() => onThemeChange(ex)}>{ex}</button>
            ))}
          </div>
        </div>

        {/* ── Commander character prompt ── */}
        <div style={s.section}>
          <label style={s.label}>
            Commander Appearance <span style={{ color: '#57534e', fontWeight: 400 }}>(optional)</span>
          </label>
          <div style={{ fontSize: 12, color: '#57534e', marginBottom: 8 }}>
            Describe <strong style={{ color: '#a8a29e' }}>{commander.name}</strong> specifically — their look, outfit, distinguishing features. This drives the commander's art and is layered on top of the world theme.
          </div>
          <textarea
            style={{ ...s.textarea, minHeight: 64 }}
            placeholder={`e.g. scarred warrior in obsidian plate armor with crimson cape and glowing rune tattoos`}
            value={commanderPrompt}
            onChange={e => onCommanderPromptChange(e.target.value)}
            rows={2}
          />
        </div>

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
            {[
              { label: '🌿 Vine',    kw: 'flowering vines and leaves',  col: '#4ade80' },
              { label: '❄ Frost',   kw: 'icy crystalline frost',        col: '#7dd3fc' },
              { label: '🔥 Flame',  kw: 'fire and ember sparks',        col: '#fb923c' },
              { label: '✦ Arcane', kw: 'glowing arcane sigils',         col: '#c084fc' },
              { label: '⚡ Circuit',kw: 'cyberpunk circuit traces',      col: '#22d3ee' },
              { label: '🌊 Wave',   kw: 'ocean waves and droplets',      col: '#38bdf8' },
              { label: '🌑 Shadow', kw: 'dark shadow wisps',             col: '#a78bfa' },
              { label: '🏅 Ornate', kw: 'golden baroque scrollwork',     col: '#fbbf24' },
            ].map(({ label, kw, col }) => (
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
            <div style={s.toggleLabel}>Generate card art with ComfyUI FLUX</div>
            <div style={s.toggleSlow}>
              {generateArt && !comfyOffline
                ? (hasDev && hasSchnell ? 'Dev & Schnell detected' : hasDev ? 'FLUX Dev detected' : hasSchnell ? 'FLUX Schnell detected' : 'Checkpoint detected')
                : generateArt && comfyOffline
                  ? '⚠ ComfyUI not running — start it before building'
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
                      <div style={{ fontSize: 10, color: statusColor, marginBottom: 4 }}>
                        {statusLabel}
                      </div>
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

        {/* Speed selector — only shown when art gen is on and ComfyUI is reachable */}
        {generateArt && !comfyOffline && (hasDev || hasSchnell || hasSd35) && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            {/* Quality (dev) option */}
            <button
              onClick={() => onModelSpeedChange('quality')}
              disabled={!hasDev}
              style={{
                flex: 1, padding: '10px 12px', borderRadius: 10, cursor: hasDev ? 'pointer' : 'not-allowed',
                background: modelSpeed === 'quality' ? '#1c1410' : '#0c0a09',
                border: `1px solid ${modelSpeed === 'quality' ? '#ca8a04' : '#292524'}`,
                textAlign: 'left', fontFamily: 'inherit', opacity: hasDev ? 1 : 0.4,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 700, color: modelSpeed === 'quality' ? '#eab308' : '#a8a29e', marginBottom: 3 }}>
                ✦ Quality
              </div>
              <div style={{ fontSize: 11, color: '#57534e' }}>FLUX Dev · ~30s/card · sharpest detail</div>
            </button>

            {/* SD 3.5 Large option */}
            <button
              onClick={() => onModelSpeedChange('sd35')}
              disabled={!hasSd35}
              style={{
                flex: 1, padding: '10px 12px', borderRadius: 10, cursor: hasSd35 ? 'pointer' : 'not-allowed',
                background: modelSpeed === 'sd35' ? '#100a18' : '#0c0a09',
                border: `1px solid ${modelSpeed === 'sd35' ? '#a78bfa' : '#292524'}`,
                textAlign: 'left', fontFamily: 'inherit', opacity: hasSd35 ? 1 : 0.5,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 700, color: modelSpeed === 'sd35' ? '#a78bfa' : '#a8a29e', marginBottom: 3 }}>
                ✧ SD 3.5
              </div>
              <div style={{ fontSize: 11, color: '#57534e' }}>
                {hasSd35 ? 'SD 3.5 Large · ~30s/card · alt style' : 'SD 3.5 not detected'}
              </div>
            </button>

            {/* Fast (schnell) option */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <button
                onClick={() => onModelSpeedChange('fast')}
                disabled={!hasSchnell}
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 10, cursor: hasSchnell ? 'pointer' : 'not-allowed',
                  background: modelSpeed === 'fast' ? '#0a1008' : '#0c0a09',
                  border: `1px solid ${modelSpeed === 'fast' ? '#4ade80' : '#292524'}`,
                  textAlign: 'left', fontFamily: 'inherit', opacity: hasSchnell ? 1 : 0.5,
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 700, color: modelSpeed === 'fast' ? '#4ade80' : '#a8a29e', marginBottom: 3 }}>
                  ⚡ Fast
                </div>
                <div style={{ fontSize: 11, color: '#57534e' }}>
                  {hasSchnell ? 'FLUX Schnell · ~6s/card · good quality' : 'FLUX Schnell not detected'}
                </div>
              </button>
              {!hasSchnell && (
                <div style={{ fontSize: 10, color: '#44403c', lineHeight: 1.5, paddingLeft: 2 }}>
                  Download{' '}
                  <a
                    href="https://huggingface.co/Comfy-Org/flux1-schnell/blob/main/flux1-schnell-fp8.safetensors"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: '#78716c', textDecoration: 'underline' }}
                  >
                    flux1-schnell-fp8.safetensors
                  </a>
                  {' '}→ place in <span style={{ color: '#57534e' }}>ComfyUI/models/checkpoints/</span>
                </div>
              )}
            </div>
          </div>
        )}

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
