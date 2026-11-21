// All map code lives here, framework-free. React only creates the view and calls its setters.
// Setters can be called before the style is loaded: the latest data is applied on load.
import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, Map as MlMap, StyleSpecification } from 'maplibre-gl'
import type { Feature, FeatureCollection } from 'geojson'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import type { Grid, PlanUpdated, Position, RoutePoint, Scenario, Zone } from '../api/protocol'
import { gridBounds, type ZoneState } from '../domain/view'

// Draft basemap: online OSM raster tiles. TODO: offline PMTiles extract of the demo area.
const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#1a1b1e' } },
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
      paint: { 'raster-saturation': -0.7, 'raster-brightness-max': 0.65 },
    },
  ],
}

export const COLORS = {
  friendlyOn: '#e03131',
  friendlyCut: '#2f9e44',
  friendlyPending: '#f08c00',
  enemy: '#9c36b5',
  radar: '#fd7e14',
  baseline: '#adb5bd',
  optimised: '#22b8cf',
  preview: '#f08c00',
  fallback: '#fa5252',
  drone: '#ffffff',
}

/** Colour of the planned route for each plan status. */
export const ROUTE_COLORS: Record<PlanUpdated['status'], string> = {
  baseline: COLORS.optimised,
  approved: COLORS.optimised,
  preview: COLORS.preview,
  fallback: COLORS.fallback,
}

/** Drone updates arrive about every 500 ms: glide to each one over slightly less. */
const DRONE_GLIDE_MS = 450
/** Beyond this jump (new route, reconnect), place the drone instead of gliding. */
const DRONE_SNAP_M = 2000

type FC = FeatureCollection
const empty = (): FC => ({ type: 'FeatureCollection', features: [] })

export interface DroneDisplayOpts {
  glide?: boolean
  headingDeg?: number | null
  action?: RoutePoint['action'] | null
  isLive?: boolean
}

export interface LayerVisibility {
  zones?: boolean
  baseline?: boolean
  grid?: boolean
  rf?: boolean
  heatmap?: boolean
  relief?: boolean
}

export interface MapView {
  setScene(scenario: Scenario, grid: Grid, zones: Zone[]): void
  setZoneStates(states: Record<string, ZoneState>): void
  /** The detour is hidden when it is the planned route itself (status baseline or fallback). */
  setRoutes(plan: PlanUpdated | null): void
  /** `glide`: animate from the shown position (live updates); otherwise jump (scrubbing). */
  setDrone(pos: Position | null, opts?: boolean | DroneDisplayOpts): void
  setRfCoverage(coverage: FeatureCollection | null): void
  setRfHeatmap(heatmap: FeatureCollection | null): void
  onHover(cb: (pos: Position | null) => void): void
  setLayerVisibility(vis: LayerVisibility): void
  set3D(enabled: boolean): void
  is3D(): boolean
  fitScene(): void
  centerOnDrone(): void
  destroy(): void
}

// MapLibre resolves its worker relative to its own module, which breaks once Vite bundles it.
maplibregl.setWorkerUrl(workerUrl)

export function createMapView(container: HTMLElement): MapView {
  const map = new maplibregl.Map({
    container,
    style: STYLE,
    center: [0, 0],
    zoom: 1,
    attributionControl: { compact: true },
    maxPitch: 85,
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-left')
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')

  let loaded = false
  let is3dMode = false
  const pending: Record<string, FC> = {}
  let grid: Grid | null = null
  let zones: Zone[] = []
  let states: Record<string, ZoneState> = {}
  let visibility: Required<LayerVisibility> = { grid: true, baseline: true, zones: true, rf: true, heatmap: false, relief: true }
  const markers: maplibregl.Marker[] = []
  let droneMarker: maplibregl.Marker | null = null
  let droneShown: Position | null = null
  let droneFrame = 0
  let droneEl: HTMLDivElement | null = null
  let droneGlyph: HTMLDivElement | null = null

  const setData = (source: string, data: FC) => {
    pending[source] = data
    if (loaded) (map.getSource(source) as GeoJSONSource | undefined)?.setData(data)
  }

  const applyVisibility = () => {
    if (!loaded) return
    const v = (on: boolean) => (on ? 'visible' : 'none')
    map.setLayoutProperty('hillshade-relief', 'visibility', v(visibility.relief))
    map.setLayoutProperty('grid-line', 'visibility', v(visibility.grid))
    map.setLayoutProperty('route-baseline', 'visibility', v(visibility.baseline))
    map.setLayoutProperty('zones-fill', 'visibility', v(visibility.zones))
    map.setLayoutProperty('zones-line', 'visibility', v(visibility.zones))
    map.setLayoutProperty('rf-coverage-fill', 'visibility', v(visibility.rf))
    map.setLayoutProperty('rf-coverage-line', 'visibility', v(visibility.rf))
    map.setLayoutProperty('rf-safe-baseline', 'visibility', v(visibility.heatmap))
    map.setLayoutProperty('rf-heatmap-cells', 'visibility', v(visibility.heatmap))
  }

  map.on('load', () => {
    // 1. Add 3D Terrarium raster-dem source
    map.addSource('terrain-dem', {
      type: 'raster-dem',
      tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
      tileSize: 256,
      encoding: 'terrarium',
      maxzoom: 15,
    })

    // 2. Global safe airspace baseline layer covering entire Earth in emerald green
    map.addSource('rf-safe-baseline', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            properties: {},
            geometry: {
              type: 'Polygon',
              coordinates: [
                [
                  [-180, -85],
                  [180, -85],
                  [180, 85],
                  [-180, 85],
                  [-180, -85],
                ],
              ],
            },
          },
        ],
      },
    })
    map.addLayer({
      id: 'rf-safe-baseline',
      type: 'fill',
      source: 'rf-safe-baseline',
      paint: {
        'fill-color': 'rgba(32, 201, 151, 0.35)', // Translucent emerald green
        'fill-opacity': 0.85,
      },
    })

    for (const id of ['grid', 'zones', 'routes', 'rf-coverage', 'rf-heatmap']) {
      map.addSource(id, { type: 'geojson', data: pending[id] ?? empty() })
    }

    // 3. Shaded relief (hillshade) layer: casts real sunlight and shadows on terrain features
    map.addLayer(
      {
        id: 'hillshade-relief',
        type: 'hillshade',
        source: 'terrain-dem',
        paint: {
          'hillshade-exaggeration': 0.85,
          'hillshade-shadow-color': '#090d16',
          'hillshade-highlight-color': '#ffffff',
          'hillshade-accent-color': '#1e293b',
          'hillshade-illumination-direction': 315,
          'hillshade-illumination-altitude': 45,
        },
      },
      'grid-line',
    )

    map.addLayer({
      id: 'grid-line',
      type: 'line',
      source: 'grid',
      paint: { 'line-color': '#868e96', 'line-width': 1, 'line-dasharray': [4, 4] },
    })

    // 4. Continuous RF heatmap polygon cells: solid contiguous quads that NEVER dilute on zoom
    map.addLayer(
      {
        id: 'rf-heatmap-cells',
        type: 'fill',
        source: 'rf-heatmap',
        paint: {
          'fill-color': ['coalesce', ['get', 'color'], '#20c997'],
          'fill-opacity': ['coalesce', ['get', 'opacity'], 0.55],
          'fill-antialias': true,
        },
      },
      'rf-coverage-fill',
    )
    map.addLayer({
      id: 'rf-coverage-fill',
      type: 'fill',
      source: 'rf-coverage',
      paint: { 'fill-color': ['get', 'fill'], 'fill-opacity': ['get', 'fill_opacity'] },
    })
    map.addLayer({
      id: 'rf-coverage-line',
      type: 'line',
      source: 'rf-coverage',
      paint: { 'line-color': ['get', 'stroke'], 'line-width': ['get', 'stroke_width'] },
    })
    map.addLayer({
      id: 'zones-fill',
      type: 'fill',
      source: 'zones',
      paint: { 'fill-color': ['get', 'color'], 'fill-opacity': ['get', 'opacity'] },
    })
    map.addLayer({
      id: 'zones-line',
      type: 'line',
      source: 'zones',
      paint: { 'line-color': ['get', 'color'], 'line-width': 2 },
    })
    map.addLayer({
      id: 'route-baseline',
      type: 'line',
      source: 'routes',
      filter: ['==', ['get', 'kind'], 'baseline'],
      paint: { 'line-color': COLORS.baseline, 'line-width': 3, 'line-dasharray': [2, 2] },
    })
    map.addLayer({
      id: 'route-optimised',
      type: 'line',
      source: 'routes',
      filter: ['==', ['get', 'kind'], 'optimised'],
      paint: { 'line-color': ['get', 'color'], 'line-width': 4 },
    })
    loaded = true
    if (is3dMode) {
      map.setTerrain({ source: 'terrain-dem', exaggeration: 2.8 })
    }
    applyVisibility()
  })

  const renderZones = () => {
    if (!grid) return
    const worldOuter = [
      [-180, -85],
      [180, -85],
      [180, 85],
      [-180, 85],
      [-180, -85],
    ]
    const features: Feature[] = zones.map((z) => {
      const ring = [...z.ring.map((p) => [p.lon, p.lat]), [z.ring[0].lon, z.ring[0].lat]]
      const { color, opacity } = zoneStyle(z, states[z.threat] ?? 'on')
      // forbidden "outside": everything but the ring, drawn with world bounds so no rectangular box appears
      const coordinates = z.forbidden === 'inside' ? [ring] : [worldOuter, ring]
      return {
        type: 'Feature',
        properties: { threat: z.threat, color, opacity },
        geometry: { type: 'Polygon', coordinates },
      }
    })
    setData('zones', { type: 'FeatureCollection', features })
  }

  return {
    setScene(scenario, g, zs) {
      grid = g
      zones = zs
      const b = gridBounds(g)
      setData('grid', {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [...b, b[0]] } }],
      })
      renderZones()
      map.fitBounds([b[0], b[2]], { padding: 30, duration: 0 })

      markers.splice(0).forEach((m) => m.remove())
      const m = scenario.mission
      markers.push(label(map, m.launch, `${m.pilot_callsign} (launch)`, '#4dabf7'))
      markers.push(label(map, m.target, 'TARGET', '#ffd43b'))
      for (const j of scenario.friendly_jammers) markers.push(label(map, j.pos, `${j.id} · ${j.operator_callsign}`, COLORS.friendlyOn))
      for (const t of scenario.enemy_threats) markers.push(label(map, t.pos, t.id, t.type === 'radar' ? COLORS.radar : COLORS.enemy))
    },
    setZoneStates(s) {
      states = s
      renderZones()
    },
    setRoutes(plan) {
      const line = (kind: string, r: RoutePoint[], color: string): Feature[] =>
        r.length > 1
          ? [{ type: 'Feature', properties: { kind, color }, geometry: { type: 'LineString', coordinates: r.map((p) => [p.lon, p.lat]) } }]
          : []
      const features = plan
        ? [
            ...(plan.status === 'preview' || plan.status === 'approved' ? line('baseline', plan.baseline_route, COLORS.baseline) : []),
            ...line('optimised', plan.optimised_route, ROUTE_COLORS[plan.status]),
          ]
        : []
      setData('routes', { type: 'FeatureCollection', features })
    },
    setRfCoverage(coverage) {
      setData('rf-coverage', coverage ?? empty())
    },
    setRfHeatmap(heatmap) {
      setData('rf-heatmap', heatmap ?? empty())
    },
    onHover(cb) {
      map.on('mousemove', (e) => {
        cb({ lat: e.lngLat.lat, lon: e.lngLat.lng })
      })
      map.on('mouseout', () => cb(null))
    },
    setDrone(pos, opts = false) {
      const isGlide = typeof opts === 'boolean' ? opts : (opts?.glide ?? false)
      const heading = typeof opts === 'object' ? opts?.headingDeg : null
      const isLive = typeof opts === 'object' ? Boolean(opts?.isLive) : false
      const action = typeof opts === 'object' ? opts?.action : null

      cancelAnimationFrame(droneFrame)
      if (!pos) {
        droneMarker?.remove()
        droneMarker = null
        droneShown = null
        droneEl = null
        droneGlyph = null
        return
      }
      if (!droneMarker) {
        const el = document.createElement('div')
        el.className = 'drone-marker'
        const pulse = document.createElement('span')
        pulse.className = 'drone-pulse'
        const glyph = document.createElement('div')
        glyph.className = 'drone-glyph'
        glyph.innerHTML =
          '<svg width="22" height="22" viewBox="0 0 24 24" fill="#22b8cf" stroke="#0b0f17" stroke-width="2" stroke-linejoin="round"><path d="M12 2 20 20l-8-4-8 4 8-18z"/></svg>'
        el.append(pulse, glyph)
        droneMarker = new maplibregl.Marker({ element: el }).setLngLat([pos.lon, pos.lat]).addTo(map)
        droneShown = pos
        droneEl = el
        droneGlyph = glyph
      }

      if (droneEl) {
        droneEl.classList.toggle('drone-live', isLive)
        droneEl.classList.toggle('drone-hover', action === 'hover')
        droneEl.classList.toggle('drone-ground', action === 'ground')
      }
      if (droneGlyph && heading !== undefined && heading !== null) {
        droneGlyph.style.transform = `rotate(${Math.round(heading)}deg)`
      }

      const from = droneShown
      if (!isGlide || !from || distanceM(from, pos) > DRONE_SNAP_M) {
        droneMarker.setLngLat([pos.lon, pos.lat])
        droneShown = pos
        return
      }
      const marker = droneMarker
      const started = performance.now()
      const step = (now: number) => {
        const f = Math.min(1, (now - started) / DRONE_GLIDE_MS)
        droneShown = { lat: from.lat + f * (pos.lat - from.lat), lon: from.lon + f * (pos.lon - from.lon) }
        marker.setLngLat([droneShown.lon, droneShown.lat])
        if (f < 1) droneFrame = requestAnimationFrame(step)
      }
      droneFrame = requestAnimationFrame(step)
    },
    setLayerVisibility(vis) {
      visibility = { ...visibility, ...vis }
      applyVisibility()
    },
    set3D(enabled: boolean) {
      is3dMode = enabled
      if (!loaded) return
      if (enabled) {
        map.setTerrain({ source: 'terrain-dem', exaggeration: 2.8 })
        map.easeTo({ pitch: 62, bearing: -20, duration: 800 })
      } else {
        map.setTerrain(null)
        map.easeTo({ pitch: 0, bearing: 0, duration: 600 })
      }
    },
    is3D() {
      return is3dMode
    },
    fitScene() {
      if (!grid) return
      const b = gridBounds(grid)
      map.fitBounds([b[0], b[2]], { padding: 48, duration: 450 })
    },
    centerOnDrone() {
      if (droneShown) {
        map.easeTo({ center: [droneShown.lon, droneShown.lat], duration: 450 })
      }
    },
    destroy() {
      cancelAnimationFrame(droneFrame)
      map.remove()
    },
  }
}

function zoneStyle(z: Zone, state: ZoneState): { color: string; opacity: number } {
  if (z.kind === 'radar') return { color: COLORS.radar, opacity: 0.2 }
  if (z.kind === 'enemy_jammer') return { color: COLORS.enemy, opacity: 0.2 }
  if (state === 'cut') return { color: COLORS.friendlyCut, opacity: 0.08 }
  if (state === 'pending') return { color: COLORS.friendlyPending, opacity: 0.18 }
  return { color: COLORS.friendlyOn, opacity: 0.22 }
}

/** HTML marker with a dot and a text label (no glyph server needed, works offline). */
function label(map: MlMap, pos: Position, text: string, color: string): maplibregl.Marker {
  const el = document.createElement('div')
  el.className = 'map-label'
  const dot = document.createElement('span')
  dot.className = 'map-label-dot'
  dot.style.background = color
  const span = document.createElement('span')
  span.textContent = text
  el.append(dot, span)
  return new maplibregl.Marker({ element: el, anchor: 'left', offset: [-6, 0] }).setLngLat([pos.lon, pos.lat]).addTo(map)
}

function distanceM(a: Position, b: Position): number {
  const dLat = (b.lat - a.lat) * 111_320
  const dLon = (b.lon - a.lon) * 111_320 * Math.cos((a.lat * Math.PI) / 180)
  return Math.hypot(dLat, dLon)
}
