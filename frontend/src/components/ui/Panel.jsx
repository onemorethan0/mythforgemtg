import { useState } from 'react'

// A titled section whose header toggles the body. `summary` is the one-line gist beside the title,
// so a collapsed section still says something. The body stays MOUNTED while collapsed (hidden, not
// removed): a panel that measures on mount or holds a result must not lose it by being closed.
//
// variant: 'box' (a bordered card) | 'row' (a slim list row, for sections whose content brings its own box)
export default function Panel({ title, summary, defaultOpen = true, variant = 'box', children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={`ui-panel ui-panel--${variant}`}>
      <button type="button" className="ui-panel__head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="ui-panel__chev" aria-hidden="true">{open ? '▾' : '▸'}</span>
        <span className="ui-panel__title">{title}</span>
        {summary && <span className="ui-panel__summary">{summary}</span>}
      </button>
      <div className="ui-panel__body" hidden={!open}>{children}</div>
    </section>
  )
}
