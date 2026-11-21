import { useEffect, useMemo, useRef } from 'react'
import { friendlyZoneState, positionAt } from '../domain/view'
import { useViewTime } from '../hooks/useSimNow'
import { createMapView, type DroneMark, type MapView } from '../map/mapView'
import { useStore } from '../store'

export function MapPanel() {
  const container = useRef<HTMLDivElement>(null)
  const view = useRef<MapView | null>(null)
  const snapshot = useStore((s) => s.snapshot)
  const cuts = useStore((s) => s.cuts)
  const missions = useStore((s) => s.missions)
  const selected = useStore((s) => s.selectedMission)
  const scrubbing = useStore((s) => s.viewTimeS !== null)
  const t = useViewTime()
  const list = useMemo(() => Object.values(missions), [missions])

  useEffect(() => {
    if (!container.current) return
    view.current = createMapView(container.current)
    return () => {
      view.current?.destroy()
      view.current = null
    }
  }, [])

  // Scene: every grid in view, the selected mission's zones over the nominal footprints. Grids
  // and zones only come with the snapshot, so plans and drones do not redraw it.
  useEffect(() => {
    if (!snapshot) return
    const constraints = snapshot.missions.map((m) => m.constraints)
    const mission = constraints.find((c) => c.mission === selected) ?? null
    view.current?.setScene({
      scenario: snapshot.scenario,
      grids: constraints.map((c) => c.grid),
      missionGrid: mission?.grid ?? null,
      missionZones: mission?.zones ?? [],
      nominalZones: snapshot.nominal_zones,
    })
  }, [snapshot, selected])

  useEffect(() => {
    if (!snapshot) return
    const all = Object.values(cuts)
    const states = Object.fromEntries(
      snapshot.scenario.friendly_jammers.map((j) => [j.id, friendlyZoneState(j.id, all, t)]),
    )
    view.current?.setZoneStates(states)
  }, [snapshot, cuts, t])

  useEffect(() => {
    view.current?.setRoutes(
      list.map((m) => ({
        mission: m.constraints.mission,
        baseline: m.plan?.baseline_route ?? null,
        optimised: m.plan?.optimised_route ?? null,
        selected: m.constraints.mission === selected,
      })),
    )
  }, [list, selected])

  // Live: the server's simulated drones. Scrubbing: where each plan puts its drone at that instant.
  useEffect(() => {
    const marks: DroneMark[] = []
    for (const m of list) {
      const mission = m.constraints.mission
      const pos = scrubbing
        ? (m.plan ? positionAt(m.plan.optimised_route, t)?.pos : undefined)
        : m.drone?.position
      if (pos) marks.push({ mission, pos, selected: mission === selected })
    }
    view.current?.setDrones(marks)
  }, [list, selected, scrubbing, t])

  return <div ref={container} className="map" />
}
