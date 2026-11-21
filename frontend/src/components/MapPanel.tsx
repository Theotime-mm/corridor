import { useEffect, useRef } from 'react'
import { friendlyZoneState, positionAt } from '../domain/view'
import { useViewTime } from '../hooks/useSimNow'
import { createMapView, type MapView } from '../map/mapView'
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
    view.current?.setRoutes(plan?.baseline_route ?? null, plan?.optimised_route ?? null)
  }, [plan])

  // Live: the server's simulated drone. Scrubbing: where the plan puts it at that instant.
  useEffect(() => {
    if (!scrubbing) {
      view.current?.setDrone(drone?.position ?? null)
      return
    }
    const at = plan ? positionAt(plan.optimised_route, t) : null
    view.current?.setDrone(at?.pos ?? null)
  }, [plan, drone, scrubbing, t])

  return <div ref={container} className="map" />
}
