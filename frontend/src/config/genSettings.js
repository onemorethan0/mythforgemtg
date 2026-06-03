// ── Generation settings schema ────────────────────────────────────────────────
// SINGLE SOURCE OF TRUTH for the per-step "Advanced" configuration panels.
// Each descriptor drives both the UI (rendered by ConfigField) and the payload
// sent to the backend. Keys MUST match server.py GenSettingsModel / image_gen
// GenSettings field names. Adding a new knob = add one entry here.
//
// field: {
//   key, step, type ('slider'|'number'|'select'|'toggle'|'lora'),
//   label, default, help?,
//   min?, max?, step?,            // slider/number
//   options?: [{value,label}],    // select
//   showIf?: (values) => boolean, // conditional visibility
// }

export const GEN_SETTINGS_SCHEMA = [
  // ── Theme step (image generation) ──────────────────────────────────────────
  {
    key: 'guidance', step: 'theme', type: 'slider',
    label: 'FLUX guidance', min: 1.5, max: 5, step: 0.1, default: 3.5,
    help: 'Higher = stronger prompt adherence but less variety. 3.5 is the FLUX-dev sweet spot; lower (≈2.5) loosens compositions.',
  },
  {
    key: 'steps', step: 'theme', type: 'slider',
    label: 'Sampler steps', min: 20, max: 40, step: 1, default: 28,
    help: 'More steps = more detail but slower. 28 is the quality/speed default for flux-dev (near-identical to 35, ~20% faster); raise toward 35 for max fidelity.',
  },
  {
    key: 'seed_mode', step: 'theme', type: 'select',
    label: 'Seed', default: 'random',
    options: [
      { value: 'random', label: 'Random (varied per card)' },
      { value: 'fixed',  label: 'Fixed (reproducible)' },
    ],
    help: 'Fixed reuses one seed so a re-run reproduces the same image.',
  },
  {
    key: 'seed', step: 'theme', type: 'number',
    label: 'Seed value', default: 0, min: 0, max: 4294967295,
    showIf: v => v.seed_mode === 'fixed',
  },
  {
    key: 'lora_overrides', step: 'theme', type: 'lora',
    label: 'LoRAs', default: null,
    help: 'Override the art-style default: pick which installed LoRAs to apply and their strength. Leave unchanged to use the style preset.',
  },
  {
    key: 'safe_mode', step: 'theme', type: 'toggle',
    label: 'Safe mode (stability)', default: false,
    help: 'Lowers steps + resolution to reduce peak GPU/CPU load — use if generation has crashed/rebooted your machine.',
  },

  // ── Face step ────────────────────────────────────────────────────────────────
  {
    key: 'face_method', step: 'face', type: 'select',
    label: 'Face method', default: 'auto',
    options: [
      { value: 'auto',       label: 'Auto (best available)' },
      { value: 'reactor',    label: 'ReActor (face swap)' },
      { value: 'pulid_flux', label: 'PuLID (FLUX identity)' },
      { value: 'none',       label: 'None (no face)' },
    ],
    help: 'How the reference photo is applied to generated characters.',
  },
  {
    key: 'face_weight', step: 'face', type: 'slider',
    label: 'Face identity strength', min: 0.5, max: 1.0, step: 0.05, default: 0.75,
    help: 'PuLID identity weight. Higher = closer to the reference face but more rigid composition.',
    showIf: v => v.face_method === 'pulid_flux' || v.face_method === 'auto',
  },
]

// Default value map derived from the schema.
export const DEFAULTS = Object.fromEntries(
  GEN_SETTINGS_SCHEMA.map(f => [f.key, f.default])
)

// All fields belonging to a given step.
export const stepFields = step => GEN_SETTINGS_SCHEMA.filter(f => f.step === step)

// Which steps actually have configurable fields (so steps without any don't render an empty panel).
export const STEPS_WITH_FIELDS = [...new Set(GEN_SETTINGS_SCHEMA.map(f => f.step))]

// Build the backend `gen_settings` payload, omitting "auto"/default sentinels that
// mean "let the backend decide" so we don't override server defaults needlessly.
export function toGenSettingsPayload(values) {
  const out = {}
  for (const f of GEN_SETTINGS_SCHEMA) {
    const v = values[f.key]
    if (v === undefined || v === null) continue
    if (f.key === 'face_method' && v === 'auto') continue          // auto → backend auto-detect
    if (f.key === 'seed') { if (values.seed_mode === 'fixed') out.seed = Number(v); continue }
    if (f.key === 'lora_overrides') {
      if (Array.isArray(v) && v.length) out.lora_overrides = v
      continue
    }
    out[f.key] = v
  }
  return out
}
