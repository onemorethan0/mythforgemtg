import { useEffect, useRef } from 'react'

// Build-completion notifier (drafted by local LLM from spec, reviewed: the draft
// overwrote the previous-status ref BEFORE comparing, so the building->done
// transition could never be detected — capture prev first, then update).
//
// On the building -> done/error transition:
//   - tab hidden: flash the tab title until the window regains focus
//   - pref on + permission granted: desktop Notification
//   - pref on: a short two-note WebAudio chime (no asset)

const PREF_KEY = 'mtg_notify_done'

export function getNotifyPref() {
  try { return localStorage.getItem(PREF_KEY) === 'on' } catch { return false }
}

export function setNotifyPref(on) {
  try { localStorage.setItem(PREF_KEY, on ? 'on' : 'off') } catch {}
}

export async function requestPermissionIfNeeded() {
  if (typeof Notification === 'undefined') return false
  if (Notification.permission === 'granted') return true
  if (Notification.permission === 'denied') return false
  try { return (await Notification.requestPermission()) === 'granted' } catch { return false }
}

function playChime() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return
    const ctx = new Ctx()
    const note = (freq, at, dur) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = freq
      osc.connect(gain)
      gain.connect(ctx.destination)
      gain.gain.setValueAtTime(0.08, ctx.currentTime + at)
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + dur)
      osc.start(ctx.currentTime + at)
      osc.stop(ctx.currentTime + at + dur)
    }
    note(660, 0, 0.12)
    note(880, 0.14, 0.18)
    setTimeout(() => { try { ctx.close() } catch {} }, 600)
  } catch {}
}

export function useBuildNotifier(status, deckName) {
  const prevRef = useRef(status)

  useEffect(() => {
    if (typeof document === 'undefined') return
    const prev = prevRef.current
    prevRef.current = status
    const finished = status === 'done' || status === 'error'
    if (prev !== 'building' || !finished) return

    let interval = null
    let onFocus = null
    const originalTitle = document.title
    const flashTitle = status === 'done' ? '✅ Deck ready!' : '⚠️ Build failed'

    if (document.hidden) {
      document.title = flashTitle
      interval = setInterval(() => {
        document.title = document.title === flashTitle ? originalTitle : flashTitle
      }, 1000)
      onFocus = () => {
        clearInterval(interval)
        interval = null
        document.title = originalTitle
        window.removeEventListener('focus', onFocus)
        onFocus = null
      }
      window.addEventListener('focus', onFocus)
    }

    if (getNotifyPref()) {
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        try {
          new Notification('Myth Forge', {
            body: status === 'done' ? `Deck ready: ${deckName || 'your deck'}` : 'Build failed',
            tag: 'mythforge-build',
          })
        } catch {}
      }
      playChime()
    }

    return () => {
      if (interval) { clearInterval(interval); document.title = originalTitle }
      if (onFocus) window.removeEventListener('focus', onFocus)
    }
  }, [status, deckName])
}
