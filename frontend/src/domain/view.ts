// Pure helpers to render any instant from the snapshot, the cuts and the last plan
// (see "Rendering on the front" in docs/architecture.md). No React, no map.
import type { Cut, Grid, Position, RoutePoint } from '../api/protocol'

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
