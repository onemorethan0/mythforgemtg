import { useEffect, useRef, useState } from 'react'
import Button from './Button'

// A button that opens a popover. Closes on an outside click and on Esc. `children` is the popover
// content, or a function `(close) => content` when an item should close the menu itself.
export default function Menu({ label, title, children, align = 'left' }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDown = e => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={box} className="ui-menu">
      <Button variant="ghost" size="sm" title={title} aria-haspopup="menu" aria-expanded={open}
              onClick={() => setOpen(o => !o)}>
        {label}
      </Button>
      {open && (
        <div role="menu" className={`ui-menu__pop ui-menu__pop--${align}`}>
          {typeof children === 'function' ? children(() => setOpen(false)) : children}
        </div>
      )}
    </div>
  )
}
