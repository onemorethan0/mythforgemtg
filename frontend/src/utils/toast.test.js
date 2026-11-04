import { describe, it, expect, beforeEach, vi } from 'vitest'

// The store is module-level state, so reload a fresh copy for each test.
let toast
beforeEach(async () => {
  vi.resetModules()
  toast = await import('./toast')
})

describe('toast store', () => {
  it('starts empty and notify returns increasing ids', () => {
    expect(toast.getToasts()).toEqual([])
    const a = toast.notify('info', 'one')
    const b = toast.notify('info', 'two')
    expect(b).toBe(a + 1)
    expect(toast.getToasts().map(t => t.message)).toEqual(['one', 'two'])
  })

  it('errors never auto-dismiss; other kinds default to six seconds and honour a custom timeout', () => {
    toast.notify('error', 'bad')
    toast.notify('success', 'ok')
    toast.notify('info', 'quick', { timeout: 1000 })
    toast.notify('error', 'still bad', { timeout: 1000 })
    const t = toast.getToasts()
    expect(t[0].timeout).toBeNull()
    expect(t[1].timeout).toBe(6000)
    expect(t[2].timeout).toBe(1000)
    expect(t[3].timeout).toBeNull()          // an error ignores the option
  })

  it('caps the visible toasts at four, keeping the newest', () => {
    for (let i = 1; i <= 7; i++) toast.notify('info', `m${i}`)
    expect(toast.getToasts().map(t => t.message)).toEqual(['m4', 'm5', 'm6', 'm7'])
  })

  it('coerces the message to a string and never throws on odd input', () => {
    expect(() => toast.notify('info', undefined)).not.toThrow()
    toast.notify('info', 42)
    toast.notify('info', null)
    expect(toast.getToasts().map(t => t.message)).toEqual(['', '42', ''])
  })

  it('subscribers get a NEW array on every change (the bug was notifying with no argument)', () => {
    const seen = []
    toast.subscribe(s => seen.push(s))
    const id = toast.notify('info', 'a')
    toast.notify('info', 'b')
    toast.dismiss(id)
    expect(seen).toHaveLength(3)
    expect(seen[0]).not.toBe(seen[1])
    expect(seen[2].map(t => t.message)).toEqual(['b'])
  })

  it('dismiss removes only that toast, and dismissing an unknown id is a silent no-op', () => {
    const a = toast.notify('info', 'a')
    toast.notify('info', 'b')
    const seen = []
    toast.subscribe(s => seen.push(s))
    toast.dismiss(999)
    expect(seen).toHaveLength(0)             // nothing changed, nothing emitted
    toast.dismiss(a)
    expect(toast.getToasts().map(t => t.message)).toEqual(['b'])
  })

  it('unsubscribe stops further notifications', () => {
    const fn = vi.fn()
    const off = toast.subscribe(fn)
    toast.notify('info', 'a')
    off()
    toast.notify('info', 'b')
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('works with no subscriber at all (a toast raised before the Toaster mounts)', () => {
    expect(() => toast.notify('error', 'early')).not.toThrow()
    expect(toast.getToasts()).toHaveLength(1)
  })
})
