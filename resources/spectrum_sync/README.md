# SPECTRUM-SYNC: 4D planner + TAK output

Plans a drone route in space and time around jammers and radars, using the friendly EW
cut schedule. Sends everything to ATAK/WinTAK/iTAK as CoT. Python 3.10+, only dependency `numpy`.

```
pip install numpy
python -m spectrum_sync plan scenarios/01_cut_confirmed.json -o out
```

## Commands

| Command | What it does |
|---|---|
| `plan SCENARIO -o out` | Plans 3 modes, prints summary, writes `out/result.json` + `out/result.geojson` (for the web map) |
| `tak test --tcp H:P` | Integration test: bot contact + one red square + one chat message |
| `tak push SCENARIO --tcp H:P` | Zones, markers, recommended + baseline routes, briefing messages |
| `tak live SCENARIO --tcp H:P --accel 10` | Plays the mission: drone moves, J3 turns green/red with the schedule, timed chat messages |
| `tak clear SCENARIO --tcp H:P` | Removes our objects from the map (demo reset) |

Transports (pick one):
- `--tcp HOST:PORT`: TAK server plain-TCP input. FreeTAKServer: 8087. OpenTAKServer: 8088.
- `--udp PHONE_IP:4242`: straight to one ATAK device, no server (ATAK's default UDP input is usually 4242).
- `--mesh`: LAN multicast, no server (SA on 239.2.3.1:6969, chat on 224.10.10.1:17012). Some Wi-Fi networks block multicast; a phone hotspot usually works.

Add `-v` to print every CoT sent.

## Tonight's test (in order of simplicity)

1. Phone with ATAK-CIV and laptop on the same Wi-Fi/hotspot.
2. `python -m spectrum_sync tak test --udp PHONE_IP:4242 --lat <your lat> --lon <your lon>`
   → a red square appears near you and a chat message from SPECTRUM-SYNC shows up.
3. If nothing appears: try `--mesh`, then a server:
   `pip install FreeTAKServer` → run it → in ATAK: Settings > Network > TAK Servers > add laptop IP, port 8087, TCP
   → `tak test --tcp LAPTOP_IP:8087`.
4. Then `tak live scenarios/01_cut_confirmed.json ... --accel 10` (about 50 s).

The demo area is in Champagne (48.95 N, 4.40 E). Change `origin` in the scenario to move it.

## Planning modes

- `baseline`: no coordination, every friendly jammer assumed ON → detour.
- `safe`: only **confirmed** cut windows are used.
- `optimistic`: **pending** windows are used too → the EW operator gets an ACK request.
Recommended = optimistic if it is better than safe (it needs the EW confirmation), else safe.

## Model (deliberately simple, all tunable in the scenario)

- **Link check per cell**: C2 uplink (receiver = drone) and video downlink (receiver = pilot).
  Blocked if J/S > `js_crit_db` (jammer powers summed) or S < `sensitivity_dbm`.
  So a jammer zone is NOT a fixed circle: it grows the further the drone is from its pilot.
- **Path loss**: free space up to `breakpoint_m`, then log-distance with `exponent` (dual-slope).
- **Radar**: detection disc (`radius_m`).
- **Time**: jammer state changes only at schedule breakpoints. Cut windows are shrunk by
  `enter_margin_s` (30 s) after start and `exit_margin_s` (60 s) before restart.
- **Search**: SIPP (Safe-Interval Path Planning) on a 100 m grid, 8-connected, fixed altitude.
  Hovering is implicit (the drone can wait inside a cell's safe interval). Time-optimal; energy =
  cruise power × flight time + hover power × hover time. About 0.1 s per plan.
- **Displayed jammer zone**: for a friendly jammer, the cells blocked *because it is on* with the others on
  (their powers add up, so this includes corridors it closes together with other jammers).

## Scenario file

See `scenarios/*.json`. Positions: `"xy": [east_m, north_m]` from `origin`, or `"lat"/"lon"`.
Times: `start_s`/`end_s` (seconds after `start_time`) or ISO `start`/`end`.
Jammer schedule: `default` on/off + `off_windows` (cuts, with `confirmed`) + `on_windows`.
Bands: `"0.4" "0.9" "1.2" "1.5" "2.4" "5.8"` or a raw MHz value.

## For the web map (result.json)

- `routes.{baseline,safe,optimistic}`: `points` (every step, with `t_s`, lat/lon), `waypoints` (turns only),
  `distance_m`, `duration_s`, `wait_s`, `energy_wh`, `battery_pct`, `crossings` (which cut window is used, enter/exit times)
- `zones`: polygons + schedule per jammer/radar
- `events`: timed notifications (`to` = `pilot` | `ew:<id>` | `all`)
- `savings`: recommended vs baseline
- `result.geojson`: the same zones and routes as GeoJSON (lon/lat), ready for MapLibre/Leaflet

## Files

```
spectrum_sync/
  scenario.py   load scenario, jammer schedule + margins
  rf.py         path loss, antenna gain, dB sums
  planner.py    masks, SIPP search, crossings, zone polygons
  mission.py    run all modes, recommendation, notifications, GeoJSON
  cot.py        CoT XML (shapes, markers, UAV, GeoChat, delete)
  tak.py        senders (TCP/UDP/mesh) + test/push/live/clear
  __main__.py   CLI
scenarios/      00 no cut, 01 confirmed cut, 02 pending cut, 03 late cut
```

## Known limits (say them before the jury does)

- Fixed altitude, flat terrain (no DEM / terrain masking yet).
- Jammer/radar positions and powers are inputs, not detected.
- Chat goes to "All Chat Rooms" (direct messages need the recipient's ATAK UID).
- CoT over plain TCP/UDP, no TLS: fine for a demo, not for the field.
