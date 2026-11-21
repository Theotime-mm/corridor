"""Run all planning modes, pick the recommended route, build notifications and exports."""
from .planner import Planner
from .scenario import MODES, Scenario


def run(sc: Scenario) -> dict:
    pl = Planner(sc)
    routes = {m: pl.plan(m) for m in MODES}
    rec = recommend(routes)
    return {
        "scenario": {
            "name": sc.name, "start_time": sc.start_time.isoformat(),
            "origin": sc.raw["origin"],
            "pilot": _pt(sc.pilot), "launch": _pt(sc.launch), "target": _pt(sc.target),
            "drone": {k: v for k, v in sc.drone.items() if k not in ("c2", "video")},
            "planning": sc.planning,
        },
        "routes": routes,
        "recommended": rec,
        "savings": savings(routes, rec),
        "zones": pl.zones(),
        "events": build_events(sc, routes, rec),
    }


def _pt(p):
    return {"callsign": p.get("callsign"), "lat": p["lat"], "lon": p["lon"], "x": p["x"], "y": p["y"]}


def recommend(routes):
    """Prefer the optimistic route if it is better and feasible (needs EW confirmation), else safe."""
    s, o = routes["safe"], routes["optimistic"]
    if o.get("feasible") and (not s.get("feasible") or o["energy_wh"] < s["energy_wh"] - 1e-6):
        return "optimistic"
    if s.get("feasible"):
        return "safe"
    return "baseline" if routes["baseline"].get("feasible") else None


def savings(routes, rec):
    b = routes["baseline"]
    if not rec or not b.get("feasible"):
        return None
    r = routes[rec]
    return {
        "vs": "baseline",
        "time_s": round(b["duration_s"] - r["duration_s"], 1),
        "distance_m": b["distance_m"] - r["distance_m"],
        "energy_wh": round(b["energy_wh"] - r["energy_wh"], 2),
        "battery_pct_points": round(b["battery_pct"] - r["battery_pct"], 1),
        "relative_pct": round(100 * (b["energy_wh"] - r["energy_wh"]) / b["energy_wh"], 1),
    }


def build_events(sc: Scenario, routes, rec):
    """Timed notifications. `to` = 'pilot' | 'ew:<jammer id>' | 'all'."""
    ev = []
    if not rec:
        ev.append({"t_s": 0, "to": "pilot", "text": "NO FEASIBLE ROUTE with current EW plan."})
        return ev
    r = routes[rec]
    uav = sc.drone.get("callsign", sc.drone.get("id", "UAV"))
    sv = savings(routes, rec)
    gain = f" (-{sv['relative_pct']:.0f}% energy vs detour)" if sv and sv["relative_pct"] > 0 else ""
    ev.append({"t_s": r["depart_s"], "to": "pilot",
               "text": f"{uav}: route ready, {r['distance_m']/1000:.1f} km, {r['duration_s']/60:.1f} min, "
                       f"battery {r['battery_pct']:.0f}%{gain}."})
    if not r["battery_ok"]:
        ev.append({"t_s": r["depart_s"], "to": "pilot", "text": f"{uav}: WARNING battery reserve not met."})
    for c in r["crossings"]:
        w, jid, cs = c["window"], c["jammer"], c["callsign"]
        if w is None:
            continue
        if not w["confirmed"]:
            ev.append({"t_s": r["depart_s"], "to": f"ew:{jid}",
                       "text": f"REQUEST {cs}: confirm OFF {w['start']}-{w['end']} for {uav} "
                               f"crossing {c['enter']}-{c['exit']}. Reply ACK {jid}."})
        else:
            ev.append({"t_s": r["depart_s"], "to": f"ew:{jid}",
                       "text": f"{cs}: OFF {w['start']}-{w['end']} confirmed. Friendly {uav} crossing "
                               f"{c['enter']}-{c['exit']}. Restart at {w['end']}."})
        ev.append({"t_s": r["depart_s"], "to": "pilot",
                   "text": f"{uav}: crossing {cs} zone {c['enter']}-{c['exit']} during cut window. "
                           f"Do not enter before {c['enter']}."})
        ev.append({"t_s": w["start_s"], "to": f"ew:{jid}", "text": f"{cs}: CUT NOW ({w['start']})."})
        ev.append({"t_s": c["enter_s"], "to": "pilot", "text": f"{uav}: entering {cs} zone, exit by {c['exit']}."})
        ev.append({"t_s": c["exit_s"], "to": "all", "text": f"{uav}: clear of {cs} zone ({c['exit']})."})
        ev.append({"t_s": w["end_s"], "to": f"ew:{jid}", "text": f"{cs}: RESTART NOW ({w['end']})."})
    ev.append({"t_s": r["arrive_s"], "to": "pilot", "text": f"{uav}: on target ({sc.hms(r['arrive_s'])})."})
    ev.sort(key=lambda e: e["t_s"])
    return ev


def to_geojson(result: dict) -> dict:
    """Flat GeoJSON for the web map (lon/lat order)."""
    feats = []
    for z in result["zones"]:
        ring = [[lon, lat] for lat, lon in z["polygon"]]
        ring.append(ring[0])
        props = {k: v for k, v in z.items() if k != "polygon"}
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"layer": "zone", **props}})
    for mode, r in result["routes"].items():
        if not r.get("feasible"):
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in r["points"]]},
                      "properties": {"layer": "route", "mode": mode,
                                     "recommended": mode == result["recommended"],
                                     "times_s": [p["t_s"] for p in r["points"]],
                                     **{k: r[k] for k in ("duration_s", "distance_m", "wait_s", "energy_wh", "battery_pct")}}})
    for role in ("pilot", "target"):
        p = result["scenario"][role]
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                      "properties": {"layer": role, "callsign": p["callsign"]}})
    return {"type": "FeatureCollection", "features": feats}
