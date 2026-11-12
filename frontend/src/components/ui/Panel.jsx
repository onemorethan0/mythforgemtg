import { useState } from 'react'

// A titled box whose header toggles the body. `summary` is the one-line gist shown beside the title
// (the workspace dock uses it so a collapsed section still says something).
export default function Panel({ title, summary, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="ui-panel">
      <button type="button" className="ui-panel__head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="ui-panel__title">{title}</span>
        {summary && <span className="ui-panel__summary">{summary}</span>}
        <span className="ui-panel__chev" aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>
      {open && <div className="ui-panel__body">{children}</div>}
    </section>
  )
}
