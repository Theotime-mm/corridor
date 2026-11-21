# Corridor

4D drone route planning synchronised with the friendly EW schedule (idea #1 in
`../edth_ideas.xlsx`, reworked). The planner computes the route, in space and time, that reaches
the target while avoiding radars and jamming zones and keeping the radio link with the pilot.
When a friendly jammer has a scheduled cut, the planner recomputes a more direct route that
crosses the zone during the cut, and notifies the pilot and the jammer operator. Goal: save the
battery a detour would cost.

No ATAK plugin: the TAK SDK is not available, so Corridor runs as an external service that
speaks CoT (Cursor on Target) to an OpenTAKServer (OTS). ATAK clients connected to the same
OTS see zones, routes and the drone as regular shapes, and what ATAK sends (shapes, chat,
positions) comes back to Corridor.

## Architecture

```
                 REST + WebSocket                                   CoT, TCP 8088
web front end ◄──────────────────► backend (Python, one process) ◄───────────────► OpenTAKServer ◄──TCP 8088──► ATAK (Android)
(planning screen)                  ├─ API + simulation clock                         │
                                   ├─ planner                                        └─ RabbitMQ / PostGIS
                                   └─ TAK bridge (corridor.tak TakClient)
```

- The backend owns all state: scenario, jammer schedules, routes, simulation time. The web front
  end and ATAK are two views of it.
- Planner: computes the routes from the scenario and the EW schedule. Algorithm and RF model are
  still being chosen by the team.
- TAK bridge: publishes zones, routes, drone position and notifications as CoT, and reads back
  what ATAK sends.
- OTS is only the relay to ATAK. The web front end never talks to OTS directly.

Status: setup only (OTS stack, CoT client, demo shapes). Backend, planner and front end are not
started in this repo.

## Front end

Planning screen used for the demo; ATAK stays the field view. Lives in `web/` (not created yet).

| Layer | Choice | Why |
|---|---|---|
| UI | React + Vite + TypeScript | Known by the team, typed contract with the backend |
| Components | Mantine | Panels, buttons, notifications, dark theme without CSS work |
| Map | MapLibre GL JS, used directly (no wrapper library) | GeoJSON layers updated in place, smooth animation, offline tiles |
| Basemap | Online tiles + an offline PMTiles extract of the demo area | The map keeps working without venue Wi-Fi |
| Timeline | vis-timeline | Draggable cut windows and a moving time cursor out of the box |
| Client state | Zustand | One small store, fed by the WebSocket |

Layout:

- Map, about 70% of the screen: jamming zones (red = active, green = cut, purple = enemy),
  radars (orange), baseline route (grey, dashed), planned route, animated drone, ATAK users'
  positions.
- Right panel: mission card (distance, time, battery vs detour), route options, approve button,
  notification feed (pilot and EW operator).
- Bottom: timeline, one row per jammer with its cut windows, plus one row for the drone showing
  when it crosses each zone. Scrubbing the timeline updates the map.

Rules:

- All map code sits in one framework-free module, `web/src/map/mapView.ts` (`setZones`,
  `setRoutes`, `setDrone`, `setPhones`, ...). React components only create the map and call it.
- The front end holds no business state: actions go to the backend over REST, state comes back
  over the WebSocket. On (re)connect the backend sends the full state, so a page reload or a
  dropped connection loses nothing.
- No internet needed at runtime: fonts, scripts and basemap are bundled.
- Demo build: `npm run build`, then the backend serves `web/dist/` as static files. One process,
  one port, no Node on the demo laptop.
- Demo controls: scenario picker, start / pause / speed, reset, a keyboard shortcut per demo
  step.

## Requirements

- Docker with the compose plugin, daemon running (`sudo systemctl enable --now docker`, user in
  the `docker` group)
- uv
- Node.js LTS (front end development only)

## Start OTS

```bash
cd infra/ots
cp ots_config.env.example ots_config.env
docker compose up -d
docker compose ps        # ots must become "healthy" (about 1 minute on first start)
docker compose logs -f ots
```

`infra/ots/compose.yml` is a trimmed copy of `brian7704/OpenTAKServer-Docker@30aa20b`. The header
of the file lists what was removed and why (no web UI, no video for now).

Images are pinned by version tag and digest: OTS 1.8.3 (2026-11-11). Do not use upstream
`:master`: it is a stale 1.5.14 build from 2025-10 that loses RabbitMQ bindings at random.
To upgrade: change the version tag in `compose.yml`, `docker compose pull`, run the smoke test
(several times, including after `docker compose up -d --force-recreate`), then re-pin with:

```bash
for img in $(docker compose config --images); do
  docker image inspect --format '{{index .RepoDigests 0}}' "$img"
done
```

First start takes 1 to 2 minutes (CA creation, database migrations). The one-shot `ots-init`
service gives the OTS user write access to the data volume, then exits.

The OTS API is published on `127.0.0.1:8081` only: `curl http://127.0.0.1:8081/api/health`.

Reset everything (deletes the OTS database and CA): `docker compose down -v`.

## Corridor CLI

```bash
uv sync
uv run corridor-tak smoke     # two connections through OTS, exit 0 if demo shapes are routed
uv run corridor-tak demo      # publish a test jam zone + corridor, refreshed every 30 s
uv run corridor-tak listen    # print every CoT routed to us
uv run corridor-tak listen --capture captures/   # also save raw XML
```

Options: `--host` (default 127.0.0.1), `--port` (8088), `--lat` / `--lon` (demo position).

## Connect ATAK

1. Phone and laptop on the same network (Wi-Fi LAN, or the same Tailscale tailnet).
2. If a firewall runs on the laptop, open TCP 8088.
3. ATAK: Settings > Network Preferences > TAK Servers > Add. Address: laptop IP, port 8088,
   protocol TCP, no SSL.
4. Run `uv run corridor-tak demo --lat <lat> --lon <lon>` near where the map is centered: a red
   jam zone, a blue corridor crossing it and an EW-1 marker appear.

## Shape format: check against a real capture

`src/corridor/tak/cot.py` builds shapes in the layout ATAK uses for drawn shapes (`u-d-f`, one
`<link point>` per vertex, signed ARGB colours). It was written from known ATAK output, not from
a schema. Before building on it:

1. `uv run corridor-tak listen --capture captures/`
2. In ATAK, draw a polygon and a line and give them a name.
3. Compare `captures/*u-d-*.xml` with what `shape()` produces and align.

## OTS notes (checked in the running OTS 1.8.3 code)

- A TCP client is registered, and only then receives other clients' CoT, after it sends an
  event carrying `<contact>`. `TakClient` sends a self SA on connect and every 30 s.
- Race in OTS: if that first SA arrives before the handler's RabbitMQ channel is open, OTS
  records the client but never binds its queues. The client can send but receives nothing,
  and nothing is logged. `TakClient` waits 1 s (`CONNECT_SETTLE_S`) before its first send
  (smoke test: 3/3 failures without the delay, 6/6 passes with it). ATAK can hit the same
  race: if it shows its own position but none of Corridor's shapes, disconnect and reconnect
  the server in ATAK.
- OTS does not echo a client's own CoT back to it.
- The OTS CA is created on first start; default admin account: `administrator` / `password`.
- Every CoT is also published to the RabbitMQ `firehose` exchange: a later option for
  consuming everything without a TCP connection.

## Development

```bash
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
```
