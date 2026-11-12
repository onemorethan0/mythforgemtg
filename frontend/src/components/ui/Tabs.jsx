import { useRef } from 'react'
import { nextTab } from './tabsNav'

// tabs: [{ key, label }]   value: the selected key   onChange(key)
// Left/Right/Home/End move the selection (and focus), as a tablist should.
export default function Tabs({ tabs, value, onChange, label = 'Sections' }) {
  const refs = useRef({})
  const keys = tabs.map(t => t.key)

  function onKeyDown(e) {
    const next = nextTab(keys, value, e.key)
    if (next !== value) {
      e.preventDefault()
      onChange(next)
      refs.current[next]?.focus()
    }
  }

  return (
    <div role="tablist" aria-label={label} className="ui-tabs" onKeyDown={onKeyDown}>
      {tabs.map(t => (
        <button key={t.key} ref={el => { refs.current[t.key] = el }} type="button" role="tab"
                className="ui-tab" aria-selected={t.key === value} tabIndex={t.key === value ? 0 : -1}
                onClick={() => onChange(t.key)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}
