import { useEffect, useState } from 'react'
import StepHome from './components/StepHome'
import StepCommander from './components/StepCommander'
import StepSingleCard from './components/StepSingleCard'
import StepCollection from './components/StepCollection'
import StepFace      from './components/StepFace'
import StepTheme     from './components/StepTheme'
import StepBuilding  from './components/StepBuilding'
import StepDeck      from './components/StepDeck'
import StepHistory   from './components/StepHistory'
import HealthIndicator from './components/HealthIndicator'
import LogViewer from './components/LogViewer'
import Toaster from './components/Toaster'
import { notify } from './utils/toast'
import { useGenSettings } from './hooks/useGenSettings'
import { toGenSettingsPayload } from './config/genSettings'

// Step indices — playstyle now lives on the Commander step (collected up front
// with bracket so the decklist can be generated before theming).
const STEP = { COMMANDER: 0, FACE: 1, THEME: 2, BUILDING: 3, DECK: 4, HISTORY: 5 }
const STEP_LABELS = ['Commander', 'Face', 'Theme', 'Building']

const SS_KEY = 'mtg_active_job'

// Compose the structured "deck vision" fields into one tight art-theme brief for
// the themer. Setting leads (claims the model's token budget); the rest are
// structured modifiers. Lighting is framed as overall atmosphere so it doesn't
// fight the per-card mana-color identity.
function composeVision(setting, moods, genres, lighting, inspiration) {
  const p = []
  if (setting && setting.trim()) p.push(setting.trim())
  if (genres && genres.length)   p.push('Genre: ' + genres.join(', '))
  if (moods && moods.length)     p.push('Mood: ' + moods.join(', '))
  if (lighting && lighting.length) p.push('Overall lighting and atmosphere: ' + lighting.join(', '))
  if (inspiration && inspiration.trim()) p.push('Inspired by ' + inspiration.trim())
  return p.join('. ')
}

// deck.json (a finished single card) -> StepSingleCard's `initial` prefill.
function cardDraftFromDeck(d) {
  const c = d.commander || {}
  const spec = d.theme_spec || {}
  return {
    name: c.original_name || '', mana_cost: c.mana_cost || '', type_line: c.original_type_line || c.type_line || '',
    oracle_text: c.oracle_text || '', flavor_text: c.flavor_text || '',
    power: c.power || '', toughness: c.toughness || '', loyalty: c.loyalty || '',
    rarity: c.rarity || 'rare', colors: c.colors || [],
    theme_mode: d.theme_mode || 'author', art_prompt_mode: d.art_prompt_mode || 'auto',
    art_prompt: c.art_prompt || '',
    setting: spec.setting || d.theme || '', moods: spec.moods || [], genres: spec.genres || [],
    lighting: spec.lighting || [], inspiration: spec.inspiration || '',
    creativity: d.creativity || 'balanced', commander_prompt: d.commander_prompt || '',
    emblem_prompt: d.emblem_prompt || '', art_style: d.art_style || 'mtg_fantasy',
    generate_art: !!d.generate_art, model_speed: d.model_speed || 'quality',
    checkpoint: d.checkpoint || '', llm_model: d.llm_model || '',
    border_theme: d.border_theme || '', frame_style: d.frame_style || 'builtin',
    custom_pips: !!d.custom_pips, face_gender: d.face_gender || 'either',
  }
}

// The payload we just POSTed -> the same prefill shape, so a failed build can
// re-open the designer exactly as the user left it.
function cardDraftFromPayload(pl) {
  const c = pl.card || {}
  const spec = pl.theme_spec || {}
  return {
    name: c.name || '', mana_cost: c.mana_cost || '', type_line: c.type_line || '',
    oracle_text: c.oracle_text || '', flavor_text: c.flavor_text || '',
    power: c.power || '', toughness: c.toughness || '', loyalty: c.loyalty || '',
    rarity: c.rarity || 'rare', colors: c.colors || [],
    theme_mode: pl.theme_mode, art_prompt_mode: pl.art_prompt_mode, art_prompt: pl.art_prompt || '',
    setting: spec.setting || '', moods: spec.moods || [], genres: spec.genres || [],
    lighting: spec.lighting || [], inspiration: spec.inspiration || '',
    creativity: pl.creativity, commander_prompt: pl.commander_prompt || '',
    emblem_prompt: pl.emblem_prompt || '', art_style: pl.art_style,
    generate_art: !!pl.generate_art, model_speed: pl.model_speed,
    checkpoint: pl.checkpoint || '', llm_model: pl.llm_model || '',
    border_theme: pl.border_theme || '', frame_style: pl.frame_style,
    custom_pips: !!pl.custom_pips, face_gender: pl.face_gender,
  }
}

export default function App() {
  const [step, setStep]           = useState(STEP.COMMANDER)
  // Landing hub picks the flow: 'home' = choose; 'deck' = the 100-card builder wizard
  // (StepCommander → Face → Theme → Building → Deck); 'card' = single custom-card designer.
  const [mode, setMode]           = useState('home')
  // Which StepCommander tab the "deck" flow opens on: 'generate' (Build) or 'import'
  // (Analyze an existing deck). Set by the home hub choice.
  const [deckEntryTab, setDeckEntryTab] = useState('generate')
  // Commander name to pre-fill the generate flow with (set by "Build this" from the
  // Collection's Buildable panel). Cleared on a fresh Home.
  const [prefillCommander, setPrefillCommander] = useState('')
  const [commander, setCommander] = useState(null)
  const [playstyle, setPlaystyle] = useState('auto')
  const [bracket, setBracket]     = useState(3)
  const [useCollection, setUseCollection] = useState(false)  // C4: build from owned cards
  // Which pool the builder may draw from: '' | 'scryfall' | 'prefer_collection' |
  // 'collection'. '' lets the server derive it from useCollection, so the existing
  // checkbox keeps meaning "prefer owned" exactly as before. Only the Collection
  // screen's "Build only from my collection" sets the strict value.
  const [cardSource, setCardSource] = useState('')
  const [theme, setTheme]         = useState('')   // the "Setting" free-text (vision anchor)
  const [creativity, setCreativity] = useState('balanced')  // Faithful ↔ Imaginative dial
  const [visionMoods, setVisionMoods]       = useState([])
  const [visionGenres, setVisionGenres]     = useState([])
  const [visionLighting, setVisionLighting] = useState([])
  const [visionInspiration, setVisionInspiration] = useState('')
  const [commanderPrompt, setCommanderPrompt] = useState('')
  const [userName, setUserName]               = useState('')
  const [emblemPrompt, setEmblemPrompt]       = useState('')
  const [customPips, setCustomPips]           = useState(false)
  const [generateArt, setGenerateArt]         = useState(false)
  const [artStyle, setArtStyle]               = useState('mtg_fantasy')
  const [modelSpeed, setModelSpeed]           = useState('quality')
  const [checkpoint, setCheckpoint]           = useState('')
  const [llmModel, setLlmModel]               = useState('qwen3:8b')
  const [borderTheme, setBorderTheme] = useState('')
  const [frameStyle, setFrameStyle] = useState('builtin')
  const [commanderTribe, setCommanderTribe] = useState('')
  // Two-phase flow: decklist generated on the Commander step, plus the deck's
  // creature tribes and the user's per-tribe replacement choices.
  const [generatedDeck, setGeneratedDeck]   = useState(null)
  const [deckTribes, setDeckTribes]         = useState([])
  const [tribalOverrides, setTribalOverrides] = useState({})
  // "Auto-theme creature types" checkbox: auto-generate one theme-fitting
  // replacement for every creature type (manual fields above still override).
  // Defaults ON so a build with no directive gets cohesive themed creature types.
  const [autoThemeTribes, setAutoThemeTribes] = useState(true)
  const [crewPrompt, setCrewPrompt] = useState('')
  const [faceKey, setFaceKey]       = useState(null)
  const [faceMethod, setFaceMethod] = useState(null)
  const [faceGender, setFaceGender] = useState('either')
  const [crewKey, setCrewKey]       = useState(null)
  const [crewGender, setCrewGender] = useState('either')
  // Imported non-Commander decks: explicit flag + the unique card list (for the
  // per-card face-assignment grid) + the chosen {cardName: personIndex} map.
  const [isCommanderDeck, setIsCommanderDeck] = useState(true)
  const [importCards, setImportCards]         = useState([])
  const [faceAssignments, setFaceAssignments] = useState({})
  // Edit & Rebuild of an IMPORTED deck: the job id whose stored card list the new
  // build must reuse verbatim. Empty for every other path.
  const [sourceDeckId, setSourceDeckId]       = useState('')
  const [jobId, setJobId]         = useState(null)
  const [deck, setDeck]           = useState(null)
  // Single-card designer: the fields to open it with. Set by "Edit this card" on a
  // finished card, and by a failed build so the user's hand-authored card isn't
  // thrown away with the error (it used to reset() straight to the home hub).
  const [cardDraft, setCardDraft] = useState(null)
  // Whether the job on the BUILDING screen is a single card. Rebuild/retheme of a
  // card clear `deck` before navigating, and a card opened from History leaves
  // `mode` on 'home', so neither is a reliable signal on its own.
  const [buildSingle, setBuildSingle] = useState(false)
  // Persisted, schema-driven Advanced generation settings (guidance/steps/LoRAs/…)
  const genSettings = useGenSettings()

  // On mount: reconnect to an in-progress or recently-completed build.
  // Primary: sessionStorage (survives refresh but not new tab).
  // Fallback: /api/deck/active (survives anything — asks the server directly).
  useEffect(() => {
    let cancelled = false

    // Ask the server what is actually running. This is the resilient path: it survives a
    // new tab, a cleared session, and a browser restart.
    function askServer() {
      return fetch('/api/deck/active').then(r => r.json()).then(d => {
        if (cancelled) return
        if (d.job_id && (d.status === 'building' || d.status === 'done')) {
          reconnect(d.job_id)
        }
      }).catch(() => {})
    }

    function reconnect(id) {
      return fetch(`/api/deck/${id}/status`).then(r => r.json()).then(d => {
        if (cancelled) return
        // 'rendering' is the on-disk checkpoint state of a job still in flight —
        // treating it as "not building" dropped the saved job on a refresh.
        if (d.status === 'building' || d.status === 'rendering') {
          _setJobId(id); setStep(STEP.BUILDING)
        } else if (d.status === 'done') {
          fetch(`/api/deck/${id}`).then(r => r.json()).then(deckData => {
            if (cancelled) return
            sessionStorage.removeItem(SS_KEY)
            setDeck(deckData); _setJobId(id); setStep(STEP.DECK)
          }).catch(() => sessionStorage.removeItem(SS_KEY))
        } else {
          sessionStorage.removeItem(SS_KEY)
        }
      })
    }

    // Try sessionStorage first
    const saved = sessionStorage.getItem(SS_KEY)
    if (saved) {
      try {
        const { id, ts } = JSON.parse(saved)
        if (id && Date.now() - ts < 3 * 60 * 60 * 1000) {
          // A FAILED status check must fall through to the server, not give up. This used
          // to `.catch(() => sessionStorage.removeItem(SS_KEY))` and return early, so the
          // /api/deck/active fallback below never ran: one unreachable moment — a refresh
          // while the server is restarting, which is the documented way to pick up a
          // Python edit — deleted the saved id and stranded a build that was still running.
          // The user landed on the home screen with a GPU busy and no route back to it.
          reconnect(id).catch(() => { if (!cancelled) askServer() })
          return () => { cancelled = true }
        }
      } catch { /* unparseable entry: fall through and ask the server */ }
      sessionStorage.removeItem(SS_KEY)
    }

    askServer()

    return () => { cancelled = true }
  }, [])

  // Persist active job ID so a page refresh can reconnect
  function _setJobId(id) {
    setJobId(id)
    if (id) sessionStorage.setItem(SS_KEY, JSON.stringify({ id, ts: Date.now() }))
    else     sessionStorage.removeItem(SS_KEY)
  }

  function reset(nextMode = 'home') {
    sessionStorage.removeItem(SS_KEY)
    setStep(STEP.COMMANDER)
    setMode(typeof nextMode === 'string' ? nextMode : 'home')
    setCardDraft(null)
    setBuildSingle(false)
    setDeckEntryTab('generate')
    setCommander(null); setPlaystyle('auto')
    setGeneratedDeck(null); setDeckTribes([]); setTribalOverrides({})
    setBracket(3); setUseCollection(false); setCardSource(''); setTheme(''); setCreativity('balanced'); setVisionMoods([]); setVisionGenres([]); setVisionLighting([]); setVisionInspiration(''); setCommanderPrompt(''); setUserName(''); setEmblemPrompt(''); setBorderTheme(''); setFrameStyle('builtin'); setCommanderTribe(''); setCrewPrompt(''); setGenerateArt(false); setArtStyle('mtg_fantasy'); setModelSpeed('quality'); setCheckpoint(''); setLlmModel('qwen3:8b')
    setFaceKey(null); setFaceMethod(null); setFaceGender('either')
    setCrewKey(null); setCrewGender('either')
    setIsCommanderDeck(true); setImportCards([]); setFaceAssignments({})
    setSourceDeckId('')
    setJobId(null); setDeck(null)
  }

  async function startBuild() {
    const res = await fetch('/api/deck/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        commander_name: commander.full_name || commander.name || "",
        deck_url:  commander._import?.mode === 'url'  ? commander._import.value : "",
        deck_list: commander._import?.mode === 'text' ? commander._import.value : "",
        // Set only by Edit & Rebuild on an imported deck — reuse that deck's exact
        // stored card list rather than re-importing or regenerating one.
        source_deck_id: sourceDeckId || "",
        playstyle,
        bracket,
        art_theme:         composeVision(theme, visionMoods, visionGenres, visionLighting, visionInspiration),
        theme_spec:        { setting: theme, moods: visionMoods, genres: visionGenres, lighting: visionLighting, inspiration: visionInspiration },
        creativity,

        commander_prompt:  commanderPrompt,
        user_name:         userName || null,
        emblem_prompt:     emblemPrompt,
        custom_pips:       customPips,
        art_style:         artStyle,
        generate_art:      generateArt,
        model_speed:       modelSpeed,
        checkpoint:        checkpoint || null,
        llm_model:         llmModel || null,
        border_theme:      borderTheme || "",
        frame_style:       frameStyle || "builtin",
        commander_tribe:   commanderTribe || "",
        prebuilt_deck:     generatedDeck || null,
        tribal_overrides:  tribalOverrides || {},
        auto_theme_tribes: autoThemeTribes,
        use_collection:    useCollection,
        card_source:       cardSource,
        face_key:     faceKey  || null,
        face_gender:  faceGender,
        crew_key:     crewKey  || null,
        crew_gender:  crewGender,
        crew_prompt:  crewPrompt || "",
        is_commander_deck: isCommanderDeck,
        face_assignments:  isCommanderDeck ? null : (faceAssignments || {}),
        gen_settings: toGenSettingsPayload(genSettings.values),
      }),
    })
    const data = await res.json()
    _setJobId(data.job_id)
    setStep(STEP.BUILDING)
  }

  // ── Single-card mode: start a custom-card build ───────────────────────────
  async function startCardBuild(payload) {
    setCardDraft(cardDraftFromPayload(payload))
    setBuildSingle(true)
    const res = await fetch('/api/card/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { const e = await res.json(); if (e.detail) detail = e.detail } catch {}
      throw new Error(detail)
    }
    const data = await res.json()
    _setJobId(data.job_id)
    setStep(STEP.BUILDING)
  }

  // ── Home hub: pick one of the three flows ─────────────────────────────────
  function handleChoose(key) {
    setPrefillCommander('')   // fresh hub entry — don't inherit a "Build this" prefill
    setCardSource('')         // ...nor a strict card_source pin from a previous visit
    if (key === 'card') {
      setMode('card')
    } else if (key === 'collection') {
      setMode('collection')
    } else {
      setMode('deck')
      setDeckEntryTab(key === 'analyze' ? 'import' : 'generate')
    }
    setStep(STEP.COMMANDER)
  }

  // "Build this" from the Collection's Buildable panel: open the generate flow with
  // the commander pre-filled and collection-aware building on. `strict` is the separate
  // "only cards I own" action — it pins card_source so the server never reaches for a
  // Scryfall staple to fill a slot the collection can't cover.
  function handleBuildFromCollection(commanderName, strict = false) {
    setPrefillCommander(commanderName || '')
    setUseCollection(true)
    setCardSource(strict ? 'collection' : '')
    setDeckEntryTab('generate')
    setMode('deck')
    setStep(STEP.COMMANDER)
  }

  // ── Face step handlers ────────────────────────────────────────────────────
  function handleFaceNext(key, method, gender, cKey, cGender, assignments) {
    setFaceKey(key)
    setFaceMethod(method)
    setFaceGender(gender || 'either')
    setCrewKey(cKey   || null)
    setCrewGender(cGender || 'either')
    setFaceAssignments(assignments || {})
    setStep(STEP.THEME)
  }
  function handleFaceSkip() {
    setFaceKey(null)
    setFaceMethod(null)
    setFaceGender('either')
    setCrewKey(null)
    setCrewGender('either')
    setFaceAssignments({})
    setStep(STEP.THEME)
  }

  // ── History step handlers ─────────────────────────────────────────────────
  function handleLoadHistoricDeck(jobId, deckData) {
    _setJobId(jobId)
    setDeck(deckData)
    setStep(STEP.DECK)
  }

  // ── Save imported deck (no art gen): fetch the freshly-saved deck and open it ──
  async function handleSaveImported(jobId) {
    try {
      const res  = await fetch(`/api/deck/${jobId}`)
      const data = await res.json()
      handleLoadHistoricDeck(jobId, data)
    } catch {
      // The deck is saved regardless; the user can open it from History.
    }
  }

  // ── Duplicate handler (navigate to the copy immediately) ────────────────
  async function handleDuplicate(newJobId) {
    try {
      const res  = await fetch(`/api/deck/${newJobId}`)
      const data = await res.json()
      _setJobId(newJobId)
      setDeck(data)
      // Stay on DECK step — user now views the copy
    } catch {
      // If fetch fails the copy still exists; user can find it in History
    }
  }

  // ── Resume building handler (reconnect to in-progress build) ───────────────
  function handleResumeBuilding(jobId) {
    _setJobId(jobId)
    setStep(STEP.BUILDING)
  }

  // ── Rebuild handler (re-run art gen from StepDeck) ───────────────────────
  function handleRebuild(newJobId) {
    // Clear the old deck so StepBuilding/StepDeck don't show stale data
    setBuildSingle(deck?.mode === 'single_card')
    setDeck(null)
    _setJobId(newJobId)
    setStep(STEP.BUILDING)
  }

  // ── Retheme handler (full re-generation: new theming AND new art) ────────
  function handleRetheme(newJobId) {
    setBuildSingle(deck?.mode === 'single_card')
    setDeck(null)
    _setJobId(newJobId)
    setStep(STEP.BUILDING)
  }

  // ── Edit & Rebuild: re-enter the wizard with this deck's settings prefilled ──
  // Lands on the Theme step (where most regeneration knobs live) with the
  // commander reconstructed and every parameter pre-populated for editing.
  // Building from here creates a NEW deck — the original is left untouched.
  async function handleEditDeck(d) {
    if (!d) return

    if (d.mode === 'single_card') {
      setCardDraft(cardDraftFromDeck(d))
      _setJobId(null)
      setDeck(null)
      setMode('card')
      setStep(STEP.COMMANDER)
      return
    }

    // An IMPORTED deck's card list is the deck's identity, and this wizard offers no
    // way to change it — only the theme/art. So pin the deck being edited and let the
    // build reuse its stored list verbatim. Without this the payload carried no
    // deck_url/deck_list (they aren't restorable here) and no prebuilt_deck, so the
    // build fell through to the GENERATE branch and DeckBuilder silently replaced the
    // user's imported deck with a different 99-card pile.
    setSourceDeckId(d.imported ? (jobId || '') : '')

    // Reconstruct the commander card the wizard expects from stored deck data.
    const cmd = d.commander || {}
    setCommander({
      name:        cmd.original_name || '',
      full_name:   cmd.original_name || '',
      mana_cost:   cmd.mana_cost || '',
      type_line:   cmd.type_line || '',
      oracle_text: cmd.oracle_text || '',
      colors:      cmd.colors || [],
      image_url:   cmd.scryfall_img || '',
      legal:       true,
    })

    // deck.json persists the playstyle LABEL; reverse-map it back to its key
    // so the Playstyle step shows the original selection. Falls back to 'auto'.
    let psKey = 'auto'
    try {
      const list  = await fetch('/api/playstyles').then(r => r.json())
      const match = (list || []).find(p => p.label === d.playstyle)
      if (match) psKey = match.key
    } catch {}
    setPlaystyle(psKey)

    setBracket(d.bracket || 3)
    // C4: a collection-built deck re-edits with the toggle still on.
    setUseCollection(!!(d.collection && d.collection.enabled))
    // Restore the structured vision fields if saved; else seed Setting with the theme.
    const spec = d.theme_spec || {}
    setTheme(spec.setting || d.theme || '')
    setCreativity(d.creativity || 'balanced')
    setVisionMoods(spec.moods || [])
    setVisionGenres(spec.genres || [])
    setVisionLighting(spec.lighting || [])
    setVisionInspiration(spec.inspiration || '')
    setCommanderPrompt(d.commander_prompt || '')
    setUserName(d.user_name || '')
    setEmblemPrompt(d.emblem_prompt || '')
    setCustomPips(!!d.custom_pips)
    setBorderTheme(d.border_theme || '')
    setFrameStyle(d.frame_style || 'builtin')
    setCommanderTribe(d.commander_tribe || '')
    // Restore ONLY the user's explicit per-tribe picks — NOT the merged effective
    // map. Restoring the full baked map froze every creature-type reskin (and the
    // creature names anchored to it) on Edit & Rebuild even when the theme changed;
    // with only explicit picks restored, auto-reskins regenerate from the new theme.
    // (Falls back to {} for decks built before this was persisted → full auto regen.)
    setTribalOverrides(d.user_tribal_overrides || {})
    setAutoThemeTribes(d.auto_theme_tribes !== false)   // default ON when unset (old decks)
    setCrewPrompt(d.crew_prompt || '')
    setGeneratedDeck(null); setDeckTribes([])
    setArtStyle(d.art_style || 'mtg_fantasy')
    // Restore the pinned style-variant from the deck's persisted gen_settings so
    // Edit & Rebuild keeps the same flavor (other advanced knobs stay in localStorage).
    genSettings.setField('style_variant', d.gen_settings?.style_variant || '')
    setGenerateArt(!!d.generate_art)
    setModelSpeed(d.model_speed || 'quality')
    setCheckpoint(d.checkpoint || '')
    setLlmModel(d.llm_model || 'qwen3:8b')
    // Preserve face/crew selection in state (the Face step can't re-display an
    // existing key, so we skip it on re-entry rather than risk nulling it).
    setFaceKey(d.face_key || null)
    setFaceMethod(null)
    setFaceGender(d.face_gender || 'either')
    setCrewKey(d.crew_key || null)
    setCrewGender(d.crew_gender || 'either')
    // Restore the Commander-deck flag; per-card assignments need photos re-uploaded
    // (face keys aren't re-displayable), so the user re-assigns on the Face step.
    setIsCommanderDeck(d.is_commander_deck !== false)
    setImportCards([]); setFaceAssignments({})

    // Fresh build → new job id; clear the old one so we don't reconnect to it.
    _setJobId(null)
    setDeck(null)
    setStep(STEP.THEME)

    // Repopulate the decklist + creature tribes so the Theme step's per-tribe
    // reskin fields show (pre-filled with the saved overrides above). Generated
    // decks only — imported decks have no DeckBuilder list to regenerate.
    if (!d.imported && (cmd.original_name || '')) {
      try {
        const gl = await fetch('/api/deck/generate-list', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ commander_name: cmd.original_name, playstyle: psKey, bracket: d.bracket || 3 }),
        }).then(r => r.ok ? r.json() : null)
        if (gl) { setGeneratedDeck(gl.deck); setDeckTribes(gl.tribes || []) }
      } catch {}
    }
  }

  // Steps shown in the progress indicator (everything before DECK). The deck
  // wizard's labelled steps don't apply to the single-card designer, so the
  // indicator is shown only in deck mode (single-card still uses BUILDING/DECK).
  const showProgress = mode === 'deck' && step >= STEP.COMMANDER && step <= STEP.BUILDING
  // The Home button appears anywhere except the landing hub itself and mid-build.
  const onHome = mode === 'home' && step === STEP.COMMANDER
  const showHome = !onHome && step !== STEP.BUILDING

  return (
    <div className="min-h-screen flex flex-col" style={{ background: '#0c0a09', color: '#f5f5f4' }}>
      {/* Header */}
      <header style={{ borderBottom: '1px solid #292524', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '22px' }}>🔨</span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <span style={{ fontSize: '18px', fontWeight: '700', letterSpacing: '0.15em', color: '#eab308', textTransform: 'uppercase' }}>
              Myth Forge
            </span>
            <span style={{ fontSize: '10px', letterSpacing: '0.05em', color: '#78716c', fontWeight: '500' }}>
              by OneMoreThan0
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <LogViewer />
          {showHome && (
            <button
              onClick={reset}
              style={{ fontSize: '13px', color: '#78716c', background: 'none', border: '1px solid #292524', borderRadius: 8, padding: '5px 12px', cursor: 'pointer' }}
            >
              🏠 Home
            </button>
          )}
          {step !== STEP.HISTORY && step !== STEP.BUILDING && (
            <button
              onClick={() => setStep(STEP.HISTORY)}
              style={{ fontSize: '13px', color: '#78716c', background: 'none', border: '1px solid #292524', borderRadius: 8, padding: '5px 12px', cursor: 'pointer' }}
            >
              📚 History
            </button>
          )}
        </div>
      </header>

      {/* Step progress indicator */}
      {showProgress && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', padding: '20px 0', alignItems: 'center' }}>
          {STEP_LABELS.map((label, i) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{
                width: '28px', height: '28px', borderRadius: '50%', display: 'flex',
                alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: '700',
                border:      i <= step ? '1px solid #ca8a04' : '1px solid #44403c',
                background:  i < step  ? '#ca8a04' : i === step ? '#eab308' : '#1c1917',
                color:       i <= step ? '#0c0a09' : '#78716c',
                transition: 'all 0.2s',
              }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: '12px', color: i === step ? '#eab308' : '#57534e' }}>
                {label}
                {/* Face step: badges for commander + crew photos */}
                {label === 'Face' && faceKey && (
                  <span style={{ marginLeft: 5, fontSize: 10, padding: '1px 5px', borderRadius: 8, background: '#eab30822', color: '#eab308', border: '1px solid #eab30844' }}>
                    👑
                  </span>
                )}
                {label === 'Face' && crewKey && (
                  <span style={{ marginLeft: 3, fontSize: 10, padding: '1px 5px', borderRadius: 8, background: '#16532422', color: '#4ade80', border: '1px solid #16532444' }}>
                    👥
                  </span>
                )}
              </span>
              {i < STEP_LABELS.length - 1 && (
                <div style={{ width: '32px', height: '1px', background: '#292524', margin: '0 4px' }} />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Content */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '0 16px 48px' }}>

        {step === STEP.COMMANDER && mode === 'home' && (
          <StepHome onChoose={handleChoose} onLoadDeck={handleLoadHistoricDeck} />
        )}

        {step === STEP.COMMANDER && mode === 'deck' && (
              <StepCommander
                initialTab={deckEntryTab}
                initialQuery={prefillCommander}
                onSaveImported={handleSaveImported}
                bracket={bracket}
                onBracketChange={setBracket}
                playstyle={playstyle}
                onPlaystyleChange={setPlaystyle}
                useCollection={useCollection}
                onUseCollectionChange={setUseCollection}
                cardSource={cardSource}
                onNext={card => {
                  setCommander(card)
                  // Generated decks carry the pre-built list + tribes from phase 1.
                  const g = card && card._generated
                  setGeneratedDeck(g ? g.deck : null)
                  setDeckTribes(g ? (g.tribes || []) : [])
                  setTribalOverrides({})
                  // Import flow carries whether it's a Commander deck + the card list
                  // for per-card face assignment. Generated decks are always commander.
                  const imp = card && card._import
                  setIsCommanderDeck(imp ? imp.is_commander_deck !== false : true)
                  setImportCards(imp ? (imp.cards || []) : [])
                  setFaceAssignments({})
                  // A fresh import/generate resolves its own list — never inherit a
                  // pin left behind by a previous Edit & Rebuild.
                  setSourceDeckId('')
                  setStep(STEP.FACE)
                }}
              />
        )}

        {step === STEP.COMMANDER && mode === 'card' && (
          <StepSingleCard
            key={cardDraft ? 'draft' : 'blank'}
            genSettings={genSettings}
            initial={cardDraft}
            onGenerate={startCardBuild}
            onBack={() => { setCardDraft(null); setMode('home') }}
          />
        )}

        {step === STEP.COMMANDER && mode === 'collection' && (
          <StepCollection onBack={() => setMode('home')} onBuild={handleBuildFromCollection} />
        )}

        {step === STEP.FACE && (
          <StepFace
            commander={commander}
            faceGender={faceGender}
            onGenderChange={setFaceGender}
            crewGender={crewGender}
            onCrewGenderChange={setCrewGender}
            isCommanderDeck={isCommanderDeck}
            importCards={importCards}
            onNext={handleFaceNext}
            onSkip={handleFaceSkip}
            onBack={() => setStep(STEP.COMMANDER)}
            genSettings={genSettings}
          />
        )}

        {step === STEP.THEME && (
          <StepTheme
            commander={commander}
            theme={theme}
            onThemeChange={setTheme}
            creativity={creativity}
            onCreativityChange={setCreativity}
            visionMoods={visionMoods} onVisionMoodsChange={setVisionMoods}
            visionGenres={visionGenres} onVisionGenresChange={setVisionGenres}
            visionLighting={visionLighting} onVisionLightingChange={setVisionLighting}
            visionInspiration={visionInspiration} onVisionInspirationChange={setVisionInspiration}
            commanderPrompt={commanderPrompt}
            onCommanderPromptChange={setCommanderPrompt}
            userName={userName}
            onUserNameChange={setUserName}
            emblemPrompt={emblemPrompt}
            onEmblemPromptChange={setEmblemPrompt}
            customPips={customPips}
            onCustomPipsChange={setCustomPips}
            artStyle={artStyle}
            onArtStyleChange={setArtStyle}
            tribes={deckTribes}
            tribalOverrides={tribalOverrides}
            onTribalOverridesChange={setTribalOverrides}
            autoThemeTribes={autoThemeTribes}
            onAutoThemeTribesChange={setAutoThemeTribes}
            generateArt={generateArt}
            onGenerateArtChange={setGenerateArt}
            modelSpeed={modelSpeed}
            onModelSpeedChange={setModelSpeed}
            checkpoint={checkpoint}
            onCheckpointChange={setCheckpoint}
            llmModel={llmModel}
            onLlmModelChange={setLlmModel}
            borderTheme={borderTheme}
            onBorderThemeChange={setBorderTheme}
            frameStyle={frameStyle}
            onFrameStyleChange={setFrameStyle}
            commanderTribe={commanderTribe}
            onCommanderTribeChange={setCommanderTribe}
            faceKey={faceKey}
            faceMethod={faceMethod}
            crewKey={crewKey}
            crewPrompt={crewPrompt}
            onCrewPromptChange={setCrewPrompt}
            genSettings={genSettings}
            onNext={startBuild}
            onBack={() => setStep(STEP.FACE)}
          />
        )}

        {step === STEP.BUILDING && (
          <StepBuilding
            jobId={jobId}
            single={buildSingle || mode === 'card'}
            onDone={deckData => { sessionStorage.removeItem(SS_KEY); setDeck(deckData); setStep(STEP.DECK) }}
            onError={msg => {
              sessionStorage.removeItem(SS_KEY)
              notify('error', `Build failed: ${msg}`)
              // Keep the card the user authored — going Home destroyed it.
              if (mode === 'card' && cardDraft) { _setJobId(null); setDeck(null); setStep(STEP.COMMANDER) }
              else reset()
            }}
          />
        )}

        {/* `deck &&` is load-bearing: StepDeck reads deck.* in its very first useState
            calls, so it cannot defend itself against a null deck from the inside without
            making its own hooks conditional. Guard here, before it mounts. */}
        {step === STEP.DECK && deck && (
          <StepDeck deck={deck} jobId={jobId} onReset={reset} onRebuild={handleRebuild} onRetheme={handleRetheme} onDuplicate={handleDuplicate} onEdit={handleEditDeck} onDeckChange={setDeck} />
        )}

        {step === STEP.HISTORY && (
          <StepHistory
            onLoad={handleLoadHistoricDeck}
            onResume={handleResumeBuilding}
            onBack={() => setStep(STEP.COMMANDER)}
          />
        )}

      </main>

      <HealthIndicator />
      <Toaster />
    </div>
  )
}
