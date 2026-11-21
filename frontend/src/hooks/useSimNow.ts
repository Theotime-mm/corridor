import { useEffect, useState } from 'react'
import { liveSimTime, useStore } from '../store'

/** Live simulated time, re-rendered `hz` times per second. */
export function useLiveSimTime(hz = 5): number {
  const clock = useStore((s) => s.clock)
  const syncedAt = useStore((s) => s.clockSyncedAt)
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    if (clock.paused) return
    const id = window.setInterval(() => setNow(performance.now()), 1000 / hz)
    return () => window.clearInterval(id)
  }, [clock.paused, hz])
  // `now` is stale right after a resync or an unpause: never extrapolate from before the sync.
  return liveSimTime(clock, syncedAt, clock.paused ? syncedAt : Math.max(now, syncedAt))
}

/** Instant shown on map and timeline: the scrubbed time, else live time. */
export function useViewTime(): number {
  const live = useLiveSimTime()
  const viewTimeS = useStore((s) => s.viewTimeS)
  return viewTimeS ?? live
}
