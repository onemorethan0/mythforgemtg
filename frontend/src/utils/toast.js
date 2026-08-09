// Toast store — deliberately NOT in Toaster.jsx.
//
// Two reasons. It keeps that file exporting only a component (react-refresh needs that to
// hot-reload it), and the store is not a component concern: any module can call notify()
// without prop-drilling or a context provider, which is what makes replacing 14 scattered
// alert() calls a one-line change at each site.
//
// Every mutation goes through _emit, which hands subscribers a NEW array. An earlier draft
// filtered the array but then notified with no argument, so the component re-set its own
// unchanged state and nothing was ever removed — dismiss looked wired up and did nothing.

const MAX_VISIBLE = 4
const DEFAULT_TIMEOUT = 6000

let _seq = 0
let _toasts = []
let _subscribers = []

function _emit() {
  const snapshot = _toasts
  _subscribers.forEach((fn) => fn(snapshot))
}

/** Current toasts. Used as the component's initial state, so a toast raised before the
 *  Toaster mounts is already on screen at first paint rather than needing a setState. */
export function getToasts() {
  return _toasts
}

export function subscribe(fn) {
  _subscribers.push(fn)
  return () => { _subscribers = _subscribers.filter((s) => s !== fn) }
}

/**
 * Raise a toast from anywhere. Never throws, works with no Toaster mounted.
 * @param {'error'|'success'|'info'} kind
 * @param {string} message
 * @param {{timeout?: number}} [opts]  ignored for 'error'
 * @returns {number} toast id
 */
export function notify(kind, message, opts = {}) {
  const id = ++_seq
  // Errors never auto-dismiss: they are the ones worth reading, and a build error that
  // vanishes after six seconds is the failure mode this replaced alert() to fix.
  const timeout = kind === 'error' ? null : (opts.timeout ?? DEFAULT_TIMEOUT)
  const next = [..._toasts, { id, kind, message: String(message ?? ''), timeout }]
  // Cap in the store, not the component, so a burst arriving before mount is bounded too.
  _toasts = next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next
  _emit()
  return id
}

export function dismiss(id) {
  const next = _toasts.filter((t) => t.id !== id)
  if (next.length === _toasts.length) return
  _toasts = next
  _emit()
}
