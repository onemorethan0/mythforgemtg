import { useEffect, useState } from 'react'
import StepCommander from './components/StepCommander'
import StepPlaystyle from './components/StepPlaystyle'
import StepFace      from './components/StepFace'
import StepTheme     from './components/StepTheme'
import StepBuilding  from './components/StepBuilding'
import StepDeck      from './components/StepDeck'
import StepHistory   from './components/StepHistory'
import HealthIndicator from './components/HealthIndicator'
import LogViewer from './components/LogViewer'
import { useGenSettings } from './hooks/useGenSettings'
import { toGenSettingsPayload } from './config/genSettings'

// Step indices
const STEP = { COMMANDER: 0, PLAYSTYLE: 1, FACE: 2, THEME: 3, BUILDING: 4, DECK: 5, HISTORY: 6 }
const STEP_LABELS = ['Commander', 'Playstyle', 'Face', 'Theme', 'Building']

const SS_KEY = 'mtg_active_job'

export default function App() {
  const [step, setStep]           = useState(STEP.COMMANDER)
  const [commander, setCommander] = useState(null)
  const [playstyle, setPlaystyle] = useState('auto')
  const [bracket, setBracket]     = useState(3)
  const [theme, setTheme]         = useState('')
  const [commanderPrompt, setCommanderPrompt] = useState('')
  const [userName, setUserName]               = useState('')
  const [emblemPrompt, setEmblemPrompt]       = useState('')
  const [generateArt, setGenerateArt]         = useState(false)
  const [artStyle, setArtStyle]               = useState('mtg_fantasy')
  const [modelSpeed, setModelSpeed]           = useState('quality')
  const [checkpoint, setCheckpoint]           = useState('')
  const [llmModel, setLlmModel]               = useState('qwen3:14b')
  const [borderTheme, setBorderTheme] = useState('')
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
    setBracket(3); setTheme(''); setCommanderPrompt(''); setUserName(''); setEmblemPrompt(''); setBorderTheme(''); setGenerateArt(false); setArtStyle('mtg_fantasy'); setModelSpeed('quality'); setCheckpoint(''); setLlmModel('qwen3:14b')
    setFaceKey(null); setFaceMethod(null); setFaceGender('either')
    setCrewKey(null); setCrewGender('either')
    setJobId(null); setDeck(null)
  }

  async function startBuild() {
    const res = await fetch('/api/deck/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        commander_name: commander.full_name || commander.name,
        playstyle,
        bracket,
        art_theme:         theme,
        commander_prompt:  commanderPrompt,
        user_name:         userName || null,
        emblem_prompt:     emblemPrompt,
        art_style:         artStyle,
        generate_art:      generateArt,
        model_speed:       modelSpeed,
        checkpoint:        checkpoint || null,
        llm_model:         llmModel || null,
        border_theme:      borderTheme || "",
        face_key:     faceKey  || null,
        face_gender:  faceGender,
        crew_key:     crewKey  || null,
        crew_gender:  crewGender,
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

  // ── Retheme handler (re-run Ollama theming, keep existing art) ───────────
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
    setTheme(d.theme || '')
    setCommanderPrompt(d.commander_prompt || '')
    setUserName(d.user_name || '')
    setEmblemPrompt(d.emblem_prompt || '')
    setBorderTheme(d.border_theme || '')
    setArtStyle(d.art_style || 'mtg_fantasy')
    setGenerateArt(!!d.generate_art)
    setModelSpeed(d.model_speed || 'quality')
    setCheckpoint(d.checkpoint || '')
    setLlmModel(d.llm_model || 'qwen3:14b')
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
          <StepCommander onNext={card => { setCommander(card); setStep(STEP.PLAYSTYLE) }} />
        )}

        {step === STEP.PLAYSTYLE && (
          <StepPlaystyle
            commander={commander}
            value={playstyle}
            onChange={setPlaystyle}
            onNext={() => setStep(STEP.FACE)}
            onBack={() => setStep(STEP.COMMANDER)}
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
            onBack={() => setStep(STEP.PLAYSTYLE)}
            genSettings={genSettings}
          />
        )}

        {step === STEP.THEME && (
          <StepTheme
            commander={commander}
            theme={theme}
            onThemeChange={setTheme}
            commanderPrompt={commanderPrompt}
            onCommanderPromptChange={setCommanderPrompt}
            userName={userName}
            onUserNameChange={setUserName}
            emblemPrompt={emblemPrompt}
            onEmblemPromptChange={setEmblemPrompt}
            artStyle={artStyle}
            onArtStyleChange={setArtStyle}
            bracket={bracket}
            onBracketChange={setBracket}
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
            faceKey={faceKey}
            faceMethod={faceMethod}
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
