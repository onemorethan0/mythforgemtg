import { useState } from 'react'
import { stepFields } from '../config/genSettings'
import ConfigField from './ConfigField'

// Collapsible "Advanced" configuration section for one workflow step.
// Renders every schema field for `step` and ALWAYS provides a
// "Reset to defaults" button (structural — never hand-rolled per section).
//
// Props: step, settings ({ values, setField, resetStep }), defaultOpen?
export default function AdvancedPanel({ step, settings, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const fields = stepFields(step)
  if (fields.length === 0) return null

  const { values, setField, resetStep } = settings
  const visible = fields.filter(f => !f.showIf || f.showIf(values))

  return (
    <div style={{ marginTop: 16, border: '1px solid #292524', borderRadius: 8, background: '#161311' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'none', border: 'none', cursor: 'pointer', padding: '10px 14px',
          color: '#a8a29e', fontSize: 13, fontFamily: 'inherit',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>⚙</span>
          Advanced settings
        </span>
        <span style={{ color: '#57534e', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}>▶</span>
      </button>

      {open && (
        <div style={{ padding: '4px 14px 14px' }}>
          {visible.map(f => (
            <ConfigField key={f.key} field={f} value={values[f.key]} onChange={setField} />
          ))}
          <button
            onClick={() => resetStep(step)}
            style={{
              marginTop: 4, fontSize: 12, color: '#78716c', background: 'none',
              border: '1px solid #292524', borderRadius: 6, padding: '5px 12px',
              cursor: 'pointer', fontFamily: 'inherit',
            }}
            title="Restore this section's fields to their default values"
          >
            ↺ Reset to defaults
          </button>
        </div>
      )}
    </div>
  )
}
