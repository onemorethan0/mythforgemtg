import { useState } from 'react'
import Tabs from './ui/Tabs'
import './workspace.css'

// The deck page as a workspace: the card list is the main column (a header and toolbar that stay
// put, a list that scrolls inside its own area), and the tools live in a dock on the right with one
// tab open at a time. Only the open tab is visible, but every tab stays MOUNTED: a Mentor
// conversation, a measurement or a swap search must survive a switch to another tab, exactly as
// they survived sitting in one long column before.
//
//   header   the always-visible strip above the list
//   toolbar  the always-visible Organize / search / view row
//   tabs     [{ key, label, content }]   the dock; the last one used is remembered
//   padBottom  leave room under the list for the fixed selection bar
export default function DeckWorkspace({ header, toolbar, tabs, children, padBottom = false }) {
  const [tab, setTab] = useState(() => {
    try {
      const saved = localStorage.getItem('mtg_dock_tab')
      return tabs.some(t => t.key === saved) ? saved : tabs[0].key
    } catch { return tabs[0].key }
  })
  const active = tabs.some(t => t.key === tab) ? tab : tabs[0].key

  function choose(key) {
    setTab(key)
    try { localStorage.setItem('mtg_dock_tab', key) } catch { /* the choice just will not persist */ }
  }

  return (
    <div className="ws">
      <div className="ws__main">
        <div className="ws__fixed">{header}{toolbar}</div>
        <div className="ws__list" style={padBottom ? { paddingBottom: 90 } : undefined}>{children}</div>
      </div>
      <aside className="ws__dock" aria-label="Deck tools">
        <Tabs tabs={tabs.map(({ key, label }) => ({ key, label }))} value={active} onChange={choose} label="Deck tools" />
        {tabs.map(t => (
          <div key={t.key} role="tabpanel" className="ws__pane" hidden={t.key !== active}>{t.content}</div>
        ))}
      </aside>
    </div>
  )
}
