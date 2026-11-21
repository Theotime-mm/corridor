import { type CSSProperties, useEffect, useRef, useState } from 'react'
import { ActionIcon, Button, Tooltip } from '@mantine/core'
import type { Position } from '../api/protocol'
import { bearingDeg, friendlyZoneState, positionAt } from '../domain/view'
import { useViewTime } from '../hooks/useSimNow'
import { COLORS, createMapView, ROUTE_COLORS, type MapView } from '../map/mapView'
import { useStore } from '../store'

export function MapPanel() {
  const container = useRef<HTMLDivElement>(null)
  const view = useRef<MapView | null>(null)
  const prevLivePos = useRef<Position | null>(null)
  const lastHeading = useRef<number | null>(null)

  const snapshot = useStore((s) => s.snapshot)
  const cuts = useStore((s) => s.cuts)
  const plan = useStore((s) => s.plan)
  const drone = useStore((s) => s.drone)
  const scrubbing = useStore((s) => s.viewTimeS !== null)
  const t = useViewTime()

  const [showZones, setShowZones] = useState(true)
  const [showBaseline, setShowBaseline] = useState(true)
  const [legendOpen, setLegendOpen] = useState(false)

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
    view.current?.setLayerVisibility({
      zones: showZones,
      baseline: showBaseline,
    })
  }, [showZones, showBaseline])

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

  // Live: the server's simulated drone, glided between its updates with heading and pulse.
  useEffect(() => {
    if (scrubbing) return
    if (!drone) {
      prevLivePos.current = null
      view.current?.setDrone(null)
      return
    }
    if (prevLivePos.current) {
      const b = bearingDeg(prevLivePos.current, drone.position)
      if (b !== null) lastHeading.current = b
    } else if (plan && plan.optimised_route.length > 1) {
      lastHeading.current = bearingDeg(plan.optimised_route[0], plan.optimised_route[1])
    }
    prevLivePos.current = drone.position
    view.current?.setDrone(drone.position, {
      glide: true,
      headingDeg: lastHeading.current,
      action: drone.action,
      isLive: true,
    })
  }, [drone, scrubbing, plan])

  // Scrubbing: where the plan puts it at that instant.
  useEffect(() => {
    if (!scrubbing) return
    const at = plan ? positionAt(plan.optimised_route, t) : null
    view.current?.setDrone(at?.pos ?? null, {
      glide: false,
      headingDeg: at?.headingDeg ?? lastHeading.current,
      action: at?.action ?? null,
      isLive: false,
    })
  }, [plan, scrubbing, t])

  return (
    <div className="map-wrap">
      <div ref={container} className="map" />

      {/* Top-Right Floating Tactical Toolbar and Legend */}
      <div className="map-hud-topright">
        <div className="map-hud-bar">
          <Button
            size="compact-xs"
            variant={showZones ? 'light' : 'subtle'}
            color={showZones ? 'cyan' : 'gray'}
            onClick={() => setShowZones((v) => !v)}
            title="Toggle jammer and radar zones"
          >
            Zones
          </Button>
          <Button
            size="compact-xs"
            variant={showBaseline ? 'light' : 'subtle'}
            color={showBaseline ? 'cyan' : 'gray'}
            onClick={() => setShowBaseline((v) => !v)}
            title="Toggle baseline detour route"
          >
            Detour
          </Button>
          <Tooltip label="Fit scenario bounds" openDelay={300}>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              aria-label="Fit scenario bounds"
              onClick={() => view.current?.fitScene()}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="9" />
                <line x1="22" y1="12" x2="18" y2="12" />
                <line x1="6" y1="12" x2="2" y2="12" />
                <line x1="12" y1="6" x2="12" y2="2" />
                <line x1="12" y1="22" x2="12" y2="18" />
              </svg>
            </ActionIcon>
          </Tooltip>
          {drone && (
            <Tooltip label="Center on drone" openDelay={300}>
              <ActionIcon
                size="sm"
                variant="subtle"
                color="cyan"
                aria-label="Center on drone"
                onClick={() => view.current?.centerOnDrone()}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="3 11 22 2 13 21 11 13 3 11" />
                </svg>
              </ActionIcon>
            </Tooltip>
          )}
          <Button
            size="compact-xs"
            variant={legendOpen ? 'filled' : 'subtle'}
            color={legendOpen ? 'cyan' : 'gray'}
            onClick={() => setLegendOpen((v) => !v)}
            title="Toggle tactical legend"
          >
            Legend
          </Button>
        </div>

        {legendOpen && (
          <div className="map-legend">
            <div className="map-legend-header">
              <span style={{ fontWeight: 700, fontSize: '11px', letterSpacing: '0.04em' }}>TACTICAL LEGEND</span>
              <button
                type="button"
                className="map-legend-close"
                onClick={() => setLegendOpen(false)}
                aria-label="Close legend"
              >
                ×
              </button>
            </div>
            {LEGEND.map((l) => (
              <div key={l.label} className="map-legend-row">
                <span className={`map-legend-key map-legend-${l.kind}`} style={{ '--c': l.color } as CSSProperties} />
                {l.label}
              </div>
            ))}
          </div>
        )}
      </div>
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
