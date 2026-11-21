"""SPECTRUM-SYNC command line.

  python -m spectrum_sync plan scenario.json [-o out]
  python -m spectrum_sync tak test  (--tcp H:P | --udp H:P | --mesh) [--lat .. --lon ..]
  python -m spectrum_sync tak push  scenario.json (--tcp H:P | --udp H:P | --mesh)
  python -m spectrum_sync tak live  scenario.json (--tcp H:P | ...) [--route safe] [--accel 10]
  python -m spectrum_sync tak clear scenario.json (--tcp H:P | ...)   # remove our objects from the map
"""
import argparse
import json
import os

from . import mission, tak
from .scenario import Scenario


def summary(res):
    lines = [f"scenario: {res['scenario']['name']}"]
    for mode, r in res["routes"].items():
        if not r.get("feasible"):
            lines.append(f"  {mode:<10} NOT FEASIBLE ({r['reason']})")
            continue
        cx = ", ".join(f"{c['jammer']} {c['enter']}-{c['exit']}"
                       f"{'' if c['window'] is None else (' confirmed' if c['window']['confirmed'] else ' PENDING')}"
                       for c in r["crossings"]) or "-"
        lines.append(f"  {mode:<10} {r['distance_m']/1000:5.1f} km  {r['duration_s']/60:5.1f} min  "
                     f"hover {r['wait_s']:4.0f}s  battery {r['battery_pct']:5.1f}%  crosses: {cx}")
    lines.append(f"recommended: {res['recommended']}")
    if res["savings"]:
        s = res["savings"]
        lines.append(f"savings vs baseline: {s['relative_pct']}% energy, {s['distance_m']/1000:.1f} km, {s['time_s']/60:.1f} min")
    lines.append("notifications:")
    lines += [f"  t+{e['t_s']:5.0f}s  {tak.chat_text(e)}" for e in res["events"]]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(prog="spectrum_sync")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="plan all modes, write result.json + result.geojson")
    p.add_argument("scenario")
    p.add_argument("-o", "--out", default="out")

    t = sub.add_parser("tak", help="send to TAK")
    t.add_argument("action", choices=["test", "push", "live", "clear"])
    t.add_argument("scenario", nargs="?")
    g = t.add_mutually_exclusive_group(required=True)
    g.add_argument("--tcp", help="TAK server HOST:PORT (FreeTAKServer 8087, OpenTAKServer 8088)")
    g.add_argument("--udp", help="device HOST:PORT (ATAK default input 4242)")
    g.add_argument("--mesh", action="store_true", help="LAN multicast, no server")
    t.add_argument("--route", choices=["baseline", "safe", "optimistic"], help="route to fly in live mode")
    t.add_argument("--accel", type=float, default=10.0, help="live mode time acceleration")
    t.add_argument("--lat", type=float, default=48.95)
    t.add_argument("--lon", type=float, default=4.40)
    t.add_argument("-v", "--verbose", action="store_true")

    a = ap.parse_args()
    if a.cmd == "plan":
        sc = Scenario.load(a.scenario)
        res = mission.run(sc)
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
        with open(os.path.join(a.out, "result.geojson"), "w", encoding="utf-8") as f:
            json.dump(mission.to_geojson(res), f)
        print(summary(res))
        print(f"\nwritten: {a.out}/result.json, {a.out}/result.geojson")
        return

    sender = tak.Sender(tcp=a.tcp, udp=a.udp, mesh=a.mesh, verbose=a.verbose)
    try:
        if a.action == "test":
            tak.cmd_test(sender, a.lat, a.lon)
            return
        if not a.scenario:
            ap.error("push/live need a scenario file")
        sc = Scenario.load(a.scenario)
        res = mission.run(sc)
        print(summary(res))
        if a.action == "push":
            tak.cmd_push(sender, res, sc)
        elif a.action == "clear":
            tak.cmd_clear(sender, res)
        else:
            tak.cmd_live(sender, res, sc, mode=a.route, accel=a.accel)
    finally:
        sender.close()


if __name__ == "__main__":
    main()
