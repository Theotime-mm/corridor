# Corridor frontend (first draft)

Planning screen. Stack and rules: root `README.md`, section "Front end". Protocol:
`docs/architecture.md`, section "WebSocket protocol".

```bash
# terminal 1, from backend/
uv run corridor-server
# terminal 2, from frontend/
npm install
npm run dev            # http://localhost:5173, /ws proxied to 127.0.0.1:8000
npm run gen:types      # after the backend regenerates schema/ws.schema.json
npm run build          # type-check + production build in dist/
```

## Layout

```
src/
  api/ws.gen.ts        generated from schema/ws.schema.json, do not edit
  api/protocol.ts      friendly names over the generated types
  api/socket.ts        WebSocket client: auto-reconnect, req_id per command
  api/client.ts        the app's single connection; send() adds the current callsign as actor
  store.ts             Zustand store: mirrors snapshot + events, plus view settings
  domain/view.ts       pure helpers: zone state at an instant, drone position on a route, grid bounds
  map/mapView.ts       all MapLibre code, framework-free (setScene, setZoneStates, setRoutes, setDrone)
  hooks/useSimNow.ts   live sim time (extrapolated between server messages), view time
  components/          TopBar, MapPanel, MissionCard, CutsCard, FeedCard, TimelinePanel
  dev/mockPlan.ts      DEV ONLY: fake plan.updated until the planner emits real ones
```

## What works

- Connects to `/ws`, renders the snapshot: grid, zones (friendly red / cut green / pending orange,
  enemy purple, radar orange; `forbidden: outside` drawn as the grid with the ring as a hole),
  launch, target, threats.
- Commands: `clock.set` (start / pause / speed), `cut.schedule`, `cut.confirm` (only enabled when
  acting as the jammer's operator), `cut.cancel`, `mission.launch`. Server errors show as an alert.
- "Acting as" picks the callsign sent as `actor` (pilot, jammer operators, HQ).
- Notification feed with the confirm button from `notification.action`.
- Timeline: cuts per jammer, drone route segments (`ground` / `fly` / `hover`), orange cursor on
  live time. Drag the cursor to scrub: map and zones follow; "Back to live" resets.
- `plan.updated`: both routes on the map, metrics in the mission card, drone interpolated on the
  optimised route. The backend does not emit it yet: use "Mock plan (dev)".

## To do

- Offline basemap (PMTiles extract of the demo area). Today: online OSM raster tiles.
- Backend serves `frontend/dist/` (static mount in `adapters/ws/app.py`).
- `drone.state` and `jammer.restarted` when the backend emits them.
- Schedule / move cuts by dragging on the timeline (today: the form in the side panel).
- Demo controls: scenario picker, reset, keyboard shortcuts.
- Bundle size: maplibre + vis-timeline + mantine in one 2 MB chunk; split if it matters.
