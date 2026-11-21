// Single client store. It only mirrors what the server says (snapshot + events) plus view
// settings (who we act as, which instant we look at). No business rule lives here.
import { create } from 'zustand'
import type { ConnStatus } from './api/socket'
import type {
  ClockState,
  Cut,
  MissionStatus,
  Notification,
  PlanUpdated,
  ServerMessage,
  Snapshot,
} from './api/protocol'

export interface FeedItem {
  id: number
  atS: number
  notification: Notification
}

interface State {
  conn: ConnStatus
  seq: number
  snapshot: Snapshot | null
  cuts: Record<string, Cut>
  clock: ClockState
  /** performance.now() when `clock` was last synced, to extrapolate live sim time. */
  clockSyncedAt: number
  missionStatus: MissionStatus
  plan: PlanUpdated | null
  feed: FeedItem[]
  lastError: string | null
  /** Callsign used as `actor` in commands. */
  actor: string
  /** Instant shown on map and timeline; null = follow the live clock. */
  viewTimeS: number | null

  setConn: (conn: ConnStatus) => void
  apply: (msg: ServerMessage) => void
  setActor: (actor: string) => void
  setViewTime: (t: number | null) => void
  setError: (reason: string | null) => void
}

let feedId = 0

export const useStore = create<State>((set, get) => ({
  conn: 'connecting',
  seq: 0,
  snapshot: null,
  cuts: {},
  clock: { sim_time_s: 0, factor: 1, paused: true },
  clockSyncedAt: performance.now(),
  missionStatus: 'planned',
  plan: null,
  feed: [],
  lastError: null,
  actor: '',
  viewTimeS: null,

  setConn: (conn) => set({ conn }),
  setActor: (actor) => set({ actor }),
  setViewTime: (viewTimeS) => set({ viewTimeS }),
  setError: (lastError) => set({ lastError }),

  apply: (msg) => {
    const p = msg.payload
    // Every envelope carries the server sim time: resync the extrapolated clock on each one.
    const clockSync = {
      clock: { ...get().clock, sim_time_s: msg.sim_time_s },
      clockSyncedAt: performance.now(),
      seq: msg.seq,
    }
    switch (p.type) {
      case 'snapshot':
        set({
          ...clockSync,
          snapshot: p,
          cuts: Object.fromEntries(p.cuts.map((c) => [c.id, c])),
          clock: p.clock,
          missionStatus: p.mission_status,
          plan: null,
          actor: get().actor || p.scenario.mission.pilot_callsign,
        })
        return
      case 'clock':
        set({ ...clockSync, clock: p.clock })
        return
      case 'cut.scheduled':
      case 'cut.confirmed':
        set({ ...clockSync, cuts: { ...get().cuts, [p.cut.id]: p.cut } })
        return
      case 'cut.cancelled': {
        const cuts = { ...get().cuts }
        delete cuts[p.cut]
        set({ ...clockSync, cuts })
        return
      }
      case 'mission.status':
        set({ ...clockSync, missionStatus: p.status })
        return
      case 'notification':
        set({
          ...clockSync,
          feed: [{ id: ++feedId, atS: msg.sim_time_s, notification: p }, ...get().feed].slice(0, 100),
        })
        return
      case 'plan.updated':
        set({ ...clockSync, plan: p })
        return
      case 'ack':
        set({ ...clockSync, lastError: null })
        return
      case 'error':
        set({ ...clockSync, lastError: p.reason })
        return
    }
  },
}))

/** Live simulated time, extrapolated from the last sync. */
export function liveSimTime(clock: ClockState, syncedAt: number, now = performance.now()): number {
  if (clock.paused) return clock.sim_time_s
  return clock.sim_time_s + ((now - syncedAt) / 1000) * clock.factor
}
