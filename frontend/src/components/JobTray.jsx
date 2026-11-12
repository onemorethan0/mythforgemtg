import { useEffect, useState, useSyncExternalStore } from 'react'
import { getJobs, subscribe, formatElapsed } from '../utils/jobs'

// Everything long-running that has been started from this page, with how long it has been going and,
// where it was measured, how long it usually takes. Visible from every dock tab, so a wait is bounded
// and findable from anywhere. It only reports: the engine cannot stop a run once begun.
export default function JobTray() {
  const jobs = useSyncExternalStore(subscribe, getJobs)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!jobs.length) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [jobs.length])

  if (!jobs.length) return null
  return (
    <div className="jobtray" role="status" aria-live="polite">
      <div className="jobtray__title">Running</div>
      {jobs.map(j => (
        <div key={j.id} className="jobtray__row">
          <span className="jobtray__label">{j.label}</span>
          <span className="jobtray__time">{formatElapsed(now - j.startedAt)}</span>
          {j.typical && <span className="jobtray__typ">usually {j.typical}</span>}
        </div>
      ))}
    </div>
  )
}
