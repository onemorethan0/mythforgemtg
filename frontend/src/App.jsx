import { useEffect, useState } from 'react'
import StepCommander from './components/StepCommander'
import StepFace      from './components/StepFace'
import StepTheme     from './components/StepTheme'
import StepBuilding  from './components/StepBuilding'
import StepDeck      from './components/StepDeck'
import StepHistory   from './components/StepHistory'
import HealthIndicator from './components/HealthIndicator'
import LogViewer from './components/LogViewer'
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

export default function App() {
  const [step, setStep]           = useState(STEP.COMMANDER)
  const [commander, setCommander] = useState(null)
  const [playstyle, setPlaystyle] = useState('auto')
  const [bracket, setBracket]     = useState(3)
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
  const [jobId, setJobId]         = useState(null)
  const [deck, setDeck]           = useState(null)
  // Persisted, schema-driven Advanced generation settings (guidance/steps/LoRAs/…)
  const genSettings = useGenSettings()

  // On mount: reconnect to an in-progress or recently-completed build.
  // Primary: sessionStorage (survives refresh but not new tab).
  // Fallback: /api/deck/active (survives anything — asks the server directly).
  useEffect(() => {
    let cancelled = false

    function reconnect(id) {
      fetch(`/api/deck/${id}/status`).then(r => r.json()).then(d => {
        if (cancelled) return
        if (d.status === 'building') {
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
      }).catch(() => sessionStorage.removeItem(SS_KEY))
    }

    // Try sessionStorage first
    const saved = sessionStorage.getItem(SS_KEY)
    if (saved) {
      try {
        const { id, ts } = JSON.parse(saved)
        if (id && Date.now() - ts < 3 * 60 * 60 * 1000) { reconnect(id); return () => { cancelled = true } }
      } catch {}
      sessionStorage.removeItem(SS_KEY)
    }

    // Fallback: ask server for active job
    fetch('/api/deck/active').then(r => r.json()).then(d => {
      if (cancelled) return
      if (d.job_id && (d.status === 'building' || d.status === 'done')) {
        reconnect(d.job_id)
      }
    }).catch(() => {})

    return () => { cancelled = true }
  }, [])

  // Persist active job ID so a page refresh can reconnect
  function _setJobId(id) {
    setJobId(id)
    if (id) sessionStorage.setItem(SS_KEY, JSON.stringify({ id, ts: Date.now() }))
    else     sessionStorage.removeItem(SS_KEY)
  }

  function reset() {
    sessionStorage.removeItem(SS_KEY)
    setStep(STEP.COMMANDER)
    setCommander(null); setPlaystyle('auto')
    setGeneratedDeck(null); setDeckTribes([]); setTribalOverrides({})
    setBracket(3); setTheme(''); setCreativity('balanced'); setVisionMoods([]); setVisionGenres([]); setVisionLighting([]); setVisionInspiration(''); setCommanderPrompt(''); setUserName(''); setEmblemPrompt(''); setBorderTheme(''); setFrameStyle('builtin'); setCommanderTribe(''); setCrewPrompt(''); setGenerateArt(false); setArtStyle('mtg_fantasy'); setModelSpeed('quality'); setCheckpoint(''); setLlmModel('qwen3:8b')
    setFaceKey(null); setFaceMethod(null); setFaceGender('either')
    setCrewKey(null); setCrewGender('either')
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
        face_key:     faceKey  || null,
        face_gender:  faceGender,
        crew_key:     crewKey  || null,
        crew_gender:  crewGender,
        crew_prompt:  crewPrompt || "",
        gen_settings: toGenSettingsPayload(genSettings.values),
      }),
    })
    const data = await res.json()
    _setJobId(data.job_id)
    setStep(STEP.BUILDING)
  }

  // ── Face step handlers ────────────────────────────────────────────────────
  function handleFaceNext(key, method, gender, cKey, cGender) {
    setFaceKey(key)
    setFaceMethod(method)
    setFaceGender(gender || 'either')
    setCrewKey(cKey   || null)
    setCrewGender(cGender || 'either')
    setStep(STEP.THEME)
  }
  function handleFaceSkip() {
    setFaceKey(null)
    setFaceMethod(null)
    setFaceGender('either')
    setCrewKey(null)
    setCrewGender('either')
    setStep(STEP.THEME)
  }

  // ── History step handlers ─────────────────────────────────────────────────
  function handleLoadHistoricDeck(jobId, deckData) {
    _setJobId(jobId)
    setDeck(deckData)
    setStep(STEP.DECK)
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
    setDeck(null)
    _setJobId(newJobId)
    setStep(STEP.BUILDING)
  }

  // ── Retheme handler (full re-generation: new theming AND new art) ────────
  function handleRetheme(newJobId) {
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

  // Steps shown in the progress indicator (everything before DECK)
  const showProgress = step >= STEP.COMMANDER && step <= STEP.BUILDING

  return (
    <div className="min-h-screen flex flex-col" style={{ background: '#0c0a09', color: '#f5f5f4' }}>
      {/* Header */}
      <header style={{ borderBottom: '1px solid #292524', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '22px' }}>⚔</span>
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
          {step !== STEP.HISTORY && step !== STEP.BUILDING && (
            <button
              onClick={() => setStep(STEP.HISTORY)}
              style={{ fontSize: '13px', color: '#78716c', background: 'none', border: '1px solid #292524', borderRadius: 8, padding: '5px 12px', cursor: 'pointer' }}
            >
              📚 History
            </button>
          )}
          {step > STEP.COMMANDER && step < STEP.BUILDING && (
            <button onClick={reset} style={{ fontSize: '13px', color: '#78716c', background: 'none', border: 'none', cursor: 'pointer' }}>
              ← Start over
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

        {step === STEP.COMMANDER && (
          <StepCommander
            bracket={bracket}
            onBracketChange={setBracket}
            playstyle={playstyle}
            onPlaystyleChange={setPlaystyle}
            onNext={card => {
              setCommander(card)
              // Generated decks carry the pre-built list + tribes from phase 1.
              const g = card && card._generated
              setGeneratedDeck(g ? g.deck : null)
              setDeckTribes(g ? (g.tribes || []) : [])
              setTribalOverrides({})
              setStep(STEP.FACE)
            }}
          />
        )}

        {step === STEP.FACE && (
          <StepFace
            commander={commander}
            faceGender={faceGender}
            onGenderChange={setFaceGender}
            crewGender={crewGender}
            onCrewGenderChange={setCrewGender}
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
            onDone={deckData => { sessionStorage.removeItem(SS_KEY); setDeck(deckData); setStep(STEP.DECK) }}
            onError={msg => { sessionStorage.removeItem(SS_KEY); alert(`Build failed: ${msg}`); reset() }}
          />
        )}

        {step === STEP.DECK && (
          <StepDeck deck={deck} jobId={jobId} onReset={reset} onRebuild={handleRebuild} onRetheme={handleRetheme} onDuplicate={handleDuplicate} onEdit={handleEditDeck} />
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
    </div>
  )
}
