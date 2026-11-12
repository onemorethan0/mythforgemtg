import { describe, it, expect } from 'vitest'
import { startJob, tracked, getJobs, subscribe, formatElapsed } from './jobs'

describe('startJob', () => {
  it('lists a running job until it is stopped', () => {
    const before = getJobs().length
    const stop = startJob('Upgrade search', { typical: 'about 6 minutes' })
    const job = getJobs().find(j => j.label === 'Upgrade search')
    expect(getJobs().length).toBe(before + 1)
    expect(job.typical).toBe('about 6 minutes')
    expect(typeof job.startedAt).toBe('number')
    stop()
    expect(getJobs().find(j => j.id === job.id)).toBeUndefined()
  })
  it('stopping twice is harmless', () => {
    const stop = startJob('a')
    stop(); stop()
    expect(getJobs().filter(j => j.label === 'a')).toHaveLength(0)
  })
  it('tells subscribers on start and on stop, and stops telling after unsubscribe', () => {
    const seen = []
    const off = subscribe(jobs => seen.push(jobs.length))
    const stop = startJob('b')
    stop()
    off()
    startJob('c')()
    expect(seen).toEqual([seen[0], seen[0] - 1])            // one on start, one on stop, none after
  })
})

describe('tracked', () => {
  it('registers the job for the duration of the call and returns its value', async () => {
    let during = 0
    const out = await tracked('t', null, async () => { during = getJobs().filter(j => j.label === 't').length; return 42 })
    expect(out).toBe(42)
    expect(during).toBe(1)
    expect(getJobs().filter(j => j.label === 't')).toHaveLength(0)
  })
  it('removes the job even when the call throws', async () => {
    await expect(tracked('boom', null, async () => { throw new Error('nope') })).rejects.toThrow('nope')
    expect(getJobs().filter(j => j.label === 'boom')).toHaveLength(0)
  })
})

describe('formatElapsed', () => {
  it('writes minutes and zero-padded seconds', () => {
    expect(formatElapsed(0)).toBe('0:00')
    expect(formatElapsed(5_000)).toBe('0:05')
    expect(formatElapsed(192_000)).toBe('3:12')
    expect(formatElapsed(3_600_000)).toBe('60:00')
  })
  it('never goes negative or throws on junk', () => {
    expect(formatElapsed(-5000)).toBe('0:00')
    expect(formatElapsed(undefined)).toBe('0:00')
  })
})
