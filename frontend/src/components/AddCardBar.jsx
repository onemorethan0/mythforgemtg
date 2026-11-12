import { useEffect, useRef, useState } from 'react'
import Button from './ui/Button'
import Chip from './ui/Chip'

// The add-a-card bar, pinned above the list: type a name, Enter adds it. "Replace" (the swap button
// on a card) puts the bar in replace mode: the next card typed takes that card's slot. Undo reverses
// the last edit. The edit itself, its busy state and its message live in StepDeck, so a remove from a
// tile and an add from here report in the same place.
//
//   replacing   the card being replaced (original name), or null
//   onAdd(name) => Promise<boolean>   true when the edit went through (the bar clears itself)
export default function AddCardBar({ replacing, busy, message, undoLabel, onAdd, onUndo, onCancelReplace }) {
  const [text, setText] = useState('')
  const [hints, setHints] = useState([])
  const inputRef = useRef(null)

  // Scryfall typeahead (debounced); the same endpoint the collection add box uses.
  useEffect(() => {
    const term = text.trim()
    if (term.length < 2) return undefined      // stale hints are hidden at render, below
    let live = true
    const t = setTimeout(() => {
      fetch(`/api/collection/suggest?q=${encodeURIComponent(term)}`)
        .then(r => (r.ok ? r.json() : { suggestions: [] }))
        .then(d => { if (live) setHints(d.suggestions || []) })
        .catch(() => {})
    }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [text])

  useEffect(() => { if (replacing) inputRef.current?.focus() }, [replacing])

  async function submit() {
    const name = text.trim()
    if (!name || busy) return
    if (await onAdd(name)) { setText(''); setHints([]) }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter') { e.preventDefault(); submit() }
    else if (e.key === 'Escape' && replacing) onCancelReplace()
  }

  return (
    <div className="addbar">
      <div className="addbar__row">
        {replacing && (
          <Chip tone="warn">
            Replacing {replacing}{' '}
            <button type="button" className="addbar__x" onClick={onCancelReplace} aria-label="Cancel replace">✕</button>
          </Chip>
        )}
        <input ref={inputRef} className="addbar__input" value={text} onChange={e => setText(e.target.value)}
               onKeyDown={onKeyDown} list="addbar-hints" aria-label={replacing ? 'Card to put in its place' : 'Card to add'}
               placeholder={replacing ? 'Type the card that takes its place, then Enter…' : 'Add a card…  (type a name, then Enter)'} />
        <datalist id="addbar-hints">{(text.trim().length >= 2 ? hints : []).map(h => <option key={h} value={h} />)}</datalist>
        <Button variant="primary" size="sm" onClick={submit} disabled={!text.trim() || busy}>
          {busy ? 'Working…' : replacing ? 'Replace' : 'Add'}
        </Button>
        <Button size="sm" onClick={onUndo} disabled={!undoLabel || busy} title={undoLabel || 'Nothing to undo'}>↶ Undo</Button>
      </div>
      {message && <div className={`addbar__msg ${message.ok ? 'addbar__msg--ok' : 'addbar__msg--bad'}`}>{message.text}</div>}
    </div>
  )
}
