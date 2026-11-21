// Pure helpers to render any instant from the snapshot, the cuts and the last plan
// (see "Rendering on the front" in docs/architecture.md). No React, no map.
import type { Cut, Grid, Position, RoutePoint, Zone } from '../api/protocol'

export type ZoneState = 'on' | 'cut' | 'pending'

/** Friendly jammer state at `t`: a confirmed cut turns it off, a scheduled one is only pending. */
export function friendlyZoneState(jammerId: string, cuts: Cut[], t: number): ZoneState {
  const covering = cuts.filter((c) => c.jammer === jammerId && c.start_s <= t && t < c.end_s)
  if (covering.some((c) => c.status === 'confirmed')) return 'cut'
  if (covering.length > 0) return 'pending'
  return 'on'
}

/** Drone position along a timed route; the action holds until the next point. */
export function positionAt(route: RoutePoint[], t: number): { pos: Position; action: RoutePoint['action'] } | null {
  if (route.length === 0) return null
  if (t <= route[0].t) return { pos: route[0], action: 'ground' }
  for (let i = 0; i < route.length - 1; i++) {
    const a = route[i]
    const b = route[i + 1]
    if (t >= a.t && t <= b.t) {
      const f = b.t === a.t ? 0 : (t - a.t) / (b.t - a.t)
      const moving = a.action === 'fly'
      return {
        pos: moving ? { lat: a.lat + f * (b.lat - a.lat), lon: a.lon + f * (b.lon - a.lon) } : a,
        action: a.action,
      }
    }
  }
  const last = route[route.length - 1]
  return { pos: last, action: last.action }
}

const M_PER_DEG_LAT = 111_320

/** Corners of the planning grid (origin = south-west corner), as [lon, lat] for GeoJSON. */
export function gridBounds(grid: Grid): [number, number][] {
  const { lat, lon } = grid.origin
  const dLat = (grid.rows * grid.cell_m) / M_PER_DEG_LAT
  const dLon = (grid.cols * grid.cell_m) / (M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180))
  return [
    [lon, lat],
    [lon + dLon, lat],
    [lon + dLon, lat + dLat],
    [lon, lat + dLat],
  ]
}

/** HH:MM:SS (UTC) of a simulated time, from the scenario start_time. */
export function clockLabel(startTime: string, t: number): string {
  return new Date(Date.parse(startTime) + t * 1000).toISOString().slice(11, 19)
}

export type PhaseKind = 'ground' | 'fly' | 'hover' | 'crossing'

/** A stretch of a route with one meaning for the timeline: on the ground, flying, hovering, or
 * inside a friendly jammer zone (`zone` set, during a cut). */
export interface Phase {
  kind: PhaseKind
  start: number
  end: number
  zone?: string
}

const PHASE_STEP_S = 2

/** Route cut into phases: consecutive segments with the same action are merged, so a turn does
 * not start a new block, and the time spent inside a friendly jammer zone is its own phase. */
export function routePhases(route: RoutePoint[], zones: Zone[]): Phase[] {
  if (route.length < 2) return []
  const friendly = zones.filter((z) => z.kind === 'friendly_jammer')
  const phases: Phase[] = []
  const t0 = route[0].t
  const t1 = route[route.length - 1].t
  for (let t = t0; t < t1; t = Math.min(t + PHASE_STEP_S, t1)) {
    const next = Math.min(t + PHASE_STEP_S, t1)
    // Sample mid-step: at a point's own time, positionAt reports the action that just ended.
    const at = positionAt(route, (t + next) / 2)
    if (!at) break
    const zone = at.action === 'ground' ? undefined : friendly.find((z) => inForbidden(z, at.pos))?.threat
    const kind: PhaseKind = zone ? 'crossing' : at.action
    const last = phases[phases.length - 1]
    if (last && last.kind === kind && last.zone === zone) last.end = next
    else phases.push({ kind, start: t, end: next, zone })
  }
  return phases
}

/** Whether `pos` lies on the forbidden side of `zone`. */
export function inForbidden(zone: Zone, pos: Position): boolean {
  const inside = inRing(zone.ring, pos)
  return zone.forbidden === 'inside' ? inside : !inside
}

/** Ray casting on lon/lat: fine at the scale of the demo area. */
function inRing(ring: Position[], p: Position): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i]
    const b = ring[j]
    if (a.lat > p.lat !== b.lat > p.lat && p.lon < ((b.lon - a.lon) * (p.lat - a.lat)) / (b.lat - a.lat) + a.lon) {
      inside = !inside
    }
  }
  return inside
}
