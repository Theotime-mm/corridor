# Resources

Material produced before and outside the main code. Not part of the `corridor` package, not
covered by ruff / mypy / pytest. Use it as reference; port what the team adopts into `src/`.

| Path | What | Use it for |
|---|---|---|
| `research.md` | Existing systems (DELTA / Mission Control, EWPMT, EMBM-J, FAAD C2, CMD3D, PARADE, NATO), field evidence, TAK access facts, with sources | Positioning, pitch slides, jury questions |
| `spectrum_sync/` | Standalone working prototype: 4D planner + CoT output (Python, numpy) | Reference implementation, demo data, quick experiments (see below) |
| `etat_de_l_art_old_scope.md` | State of the art written for the earlier chat-based deconfliction scope (French) | Bibliography (RF propagation, UTM, IEEE 1900.5.2, CoT) and the J/S argument. Scope sections are outdated; some citations are unverified, check before quoting |

## spectrum_sync: what to take

```bash
cd resources/spectrum_sync
pip install numpy
python -m spectrum_sync plan scenarios/01_cut_confirmed.json -o out   # summary + result.json + result.geojson
```

| File | Content | Status for corridor |
|---|---|---|
| `planner.py` | SIPP search over (cell, safe interval): hovering implicit, 0.1 s per plan; J/S masks; crossings (which cut a route relies on); zone outlines | Candidate planner core, if the team adopts this approach. Port to typed dataclasses for mypy strict |
| `rf.py`, `geo.py` | Dual-slope path loss, antenna gain, dB sums; local metres <-> lat/lon | Same |
| `scenario.py` | Scenario loading, jammer schedules, safety margins (30 s after cut start, 60 s before restart), confirmed vs pending windows | Same; scenario format still open |
| `mission.py` | Runs baseline / safe / optimistic, recommendation, savings, timed notifications, GeoJSON | Shape of what the backend sends to the front end |
| `tak.py` | `cmd_live`: simulation clock, drone interpolation, jammer on/off events, timed chat | Logic for the backend simulation clock. Its senders are superseded by `corridor.tak.TakClient` |
| `cot.py` | `drone()` (`a-f-A-M-F-Q` + `<track>`), `geochat()` (`b-t-f`), `delete()` (`t-x-d-d`) | Port these three into `corridor.tak.cot`; the rest is already covered there |
| `scenarios/*.json` | 4 demo cases: no cut (detour, 67% battery), confirmed cut (straight, 41%), pending cut (needs EW ACK), late cut (reshaped route + 16 s hover) | Demo story and test fixtures |
| `docs/preview.png` | Plot of the confirmed-cut case | Slide draft |
| `__main__.py` | CLI (`plan`, `tak test/push/live/clear`) | Not needed in corridor (own CLI). Still handy for a quick standalone TAK test: `python -m spectrum_sync tak test --tcp HOST:8088` |

Known limits: fixed altitude, flat terrain, jammer and radar positions given as inputs, chat to
"All Chat Rooms" only, no TLS. The shape format follows the same unverified ATAK layout as
`corridor.tak.cot`: validate both against a real capture.
