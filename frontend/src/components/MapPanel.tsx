import { type CSSProperties, useEffect, useRef } from 'react'
import { friendlyZoneState, positionAt } from '../domain/view'
import { useViewTime } from '../hooks/useSimNow'
import { COLORS, createMapView, ROUTE_COLORS, type MapView } from '../map/mapView'
import { useStore } from '../store'

export function MapPanel() {
  const container = useRef<HTMLDivElement>(null)
  const view = useRef<MapView | null>(null)
  const snapshot = useStore((s) => s.snapshot)
  const cuts = useStore((s) => s.cuts)
  const plan = useStore((s) => s.plan)
  const drone = useStore((s) => s.drone)
  const scrubbing = useStore((s) => s.viewTimeS !== null)
  const t = useViewTime()

  useEffect(() => {
    if (!container.current) return
    view.current = createMapView(container.current)
    return () => {
      view.current?.destroy()
      view.current = null
    }
  }, [])

  useEffect(() => {
    if (snapshot) view.current?.setScene(snapshot.scenario, snapshot.grid, snapshot.zones)
  }, [snapshot])

  useEffect(() => {
    if (!snapshot) return
    const list = Object.values(cuts)
    const states = Object.fromEntries(
      snapshot.scenario.friendly_jammers.map((j) => [j.id, friendlyZoneState(j.id, list, t)]),
    )
    view.current?.setZoneStates(states)
  }, [snapshot, cuts, t])

  useEffect(() => {
    view.current?.setRoutes(plan)
  }, [plan])

  // Live: the server's simulated drone, glided between its updates. Scrubbing: where the plan
  // puts it at that instant.
  useEffect(() => {
    if (!scrubbing) view.current?.setDrone(drone?.position ?? null, true)
  }, [drone, scrubbing])

  useEffect(() => {
    if (!scrubbing) return
    const at = plan ? positionAt(plan.optimised_route, t) : null
    view.current?.setDrone(at?.pos ?? null)
  }, [plan, scrubbing, t])

  return (
    <div className="map-wrap">
      <div ref={container} className="map" />
      <MapLegend />
    </div>
  )
}

const LEGEND: { label: string; color: string; kind: 'area' | 'line' | 'dash' }[] = [
  { label: 'Friendly jammer on', color: COLORS.friendlyOn, kind: 'area' },
  { label: 'Cut pending confirmation', color: COLORS.friendlyPending, kind: 'area' },
  { label: 'Cut confirmed (passable)', color: COLORS.friendlyCut, kind: 'area' },
  { label: 'Enemy jammer', color: COLORS.enemy, kind: 'area' },
  { label: 'Radar', color: COLORS.radar, kind: 'area' },
  { label: 'Detour (all jammers on)', color: COLORS.baseline, kind: 'dash' },
  { label: 'Planned route', color: ROUTE_COLORS.approved, kind: 'line' },
  { label: 'Route awaiting confirmation', color: ROUTE_COLORS.preview, kind: 'line' },
  { label: 'Fallback route', color: ROUTE_COLORS.fallback, kind: 'line' },
]

function MapLegend() {
  return (
    <div className="map-legend">
      {LEGEND.map((l) => (
        <div key={l.label} className="map-legend-row">
          <span className={`map-legend-key map-legend-${l.kind}`} style={{ '--c': l.color } as CSSProperties} />
          {l.label}
        </div>
      ))}
    </div>
  )
}
