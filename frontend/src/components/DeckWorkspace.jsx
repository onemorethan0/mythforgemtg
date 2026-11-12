import { useEffect, useState, useSyncExternalStore } from 'react'
import Tabs from './ui/Tabs'
import JobTray from './JobTray'
import { sheetTabAction } from './ui/sheetNav'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { getJobs, subscribe } from '../utils/jobs'
import './workspace.css'

// The deck page as a workspace: the card list is the main column (a header and toolbar that stay
// put, a list that scrolls inside its own area), and the tools live in a dock on the right with one
// tab open at a time. Only the open tab is visible, but every tab stays MOUNTED: a Mentor
// conversation, a measurement or a swap search must survive a switch to another tab, exactly as
// they survived sitting in one long column before.
//
// On a narrow window (900px and under) the dock becomes a bottom sheet instead: the tab strip is a
// launcher along the bottom edge, tapping a tab opens the sheet on it and tapping it again folds it
// away, so the tools are never pushed below the whole card list.
//
//   header   the always-visible strip above the list
//   bar      the add-a-card bar, pinned under the header
//   toolbar  the always-visible Organize / search / view row
//   tabs     [{ key, label, content }]   the dock; the last one used is remembered
//   padBottom  leave room under the list for the fixed selection bar
export default function DeckWorkspace({ header, bar, toolbar, tabs, children, padBottom = false }) {
  const [tab, setTab] = useState(() => {
    try {
      const saved = localStorage.getItem('mtg_dock_tab')
      return tabs.some(t => t.key === saved) ? saved : tabs[0].key
    } catch { return tabs[0].key }
  })
  const active = tabs.some(t => t.key === tab) ? tab : tabs[0].key
  const narrow = useMediaQuery('(max-width: 900px)')
  const [sheetOpen, setSheetOpen] = useState(false)
  const open = narrow && sheetOpen
  const jobs = useSyncExternalStore(subscribe, getJobs)

  function remember(key) {
    try { localStorage.setItem('mtg_dock_tab', key) } catch { /* the choice just will not persist */ }
  }

  function choose(key) {
    if (narrow) {
      const next = sheetTabAction(active, key, sheetOpen)
      setTab(next.tab); setSheetOpen(next.open); remember(next.tab)
    } else {
      setTab(key); remember(key)
    }
  }

  useEffect(() => {
    if (!open) return undefined
    const onKey = e => { if (e.key === 'Escape') setSheetOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const dockClass = `ws__dock${narrow ? ' ws__dock--sheet' : ''}${narrow && !open ? ' is-collapsed' : ''}`

  return (
    <div className={`ws${narrow ? ' ws--narrow' : ''}`}>
      <div className="ws__main">
        <div className="ws__fixed">{header}{bar}{toolbar}</div>
        <div className="ws__list" style={padBottom ? { paddingBottom: 90 } : undefined}>{children}</div>
      </div>
      <aside className={dockClass} aria-label="Deck tools" style={narrow && padBottom ? { bottom: 64 } : undefined}>
        <Tabs tabs={tabs.map(({ key, label }) => ({ key, label }))} value={active} onChange={choose} label="Deck tools" />
        {narrow && !open && jobs.length > 0 && (
          <span className="ws__badge" role="status">⏳ {jobs.length} running</span>
        )}
        {open && (
          <button type="button" className="ws__sheet-close" onClick={() => setSheetOpen(false)} aria-label="Close tools">✕</button>
        )}
        {tabs.map(t => (
          <div key={t.key} role="tabpanel" className="ws__pane" hidden={t.key !== active}>{t.content}</div>
        ))}
        <div className="ws__tray"><JobTray /></div>
      </aside>
    </div>
  )
}
