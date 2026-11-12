// A tiny store of the long-running jobs the panels start (a measurement, an upgrade search, a
// scouting report ...), so one tray can show everything that is running, wherever it was started.
// Not a scheduler and not a cancel button: a panel registers a job while its request is in flight
// and the store only reports it. (The server has no way to stop an engine run once it has begun,
// so a "cancel" here would only stop WAITING, and the work would carry on: it is deliberately not
// offered.)

let _jobs = []
let _subs = []
let _seq = 0

function emit() {
  _subs.forEach(fn => fn(_jobs))
}

export function getJobs() {
  return _jobs
}

export function subscribe(fn) {
  _subs.push(fn)
  return () => { _subs = _subs.filter(s => s !== fn) }
}

/** Register a running job. Returns the function that ends it (idempotent). `typical` is a short
 *  phrase for how long it usually takes ("about 6 minutes"), shown only when it was measured. */
export function startJob(label, opts) {
  const id = ++_seq
  _jobs = [..._jobs, { id, label, typical: opts?.typical ?? null, startedAt: Date.now() }]
  emit()
  return () => {
    const next = _jobs.filter(j => j.id !== id)
    if (next.length !== _jobs.length) { _jobs = next; emit() }
  }
}

/** Run `fn` as a tracked job: registered before it starts, removed when it settles either way. */
export async function tracked(label, opts, fn) {
  const stop = startJob(label, opts)
  try {
    return await fn()
  } finally {
    stop()
  }
}

/** 192000 -> "3:12" */
export function formatElapsed(ms) {
  const s = Math.max(0, Math.floor((Number(ms) || 0) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
