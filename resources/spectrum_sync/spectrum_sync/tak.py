"""Send planner output to TAK clients.

Transports (pick one):
  --tcp HOST:PORT   TAK server plain TCP input (FreeTAKServer default 8087, OpenTAKServer 8088)
  --udp HOST:PORT   UDP straight to one device (ATAK usually listens on 4242/udp)
  --mesh            LAN multicast, no server: SA 239.2.3.1:6969, chat 224.10.10.1:17012
"""
import math
import socket
import time

from . import cot
from .scenario import Scenario

MESH_SA = ("239.2.3.1", 6969)
MESH_CHAT = ("224.10.10.1", 17012)


def _hostport(s):
    host, port = s.rsplit(":", 1)
    return host, int(port)


class Sender:
    def __init__(self, tcp=None, udp=None, mesh=False, verbose=False):
        if sum(bool(x) for x in (tcp, udp, mesh)) != 1:
            raise ValueError("choose exactly one transport: --tcp, --udp or --mesh")
        self.tcp, self.udp, self.mesh, self.verbose = tcp, udp, mesh, verbose
        self.sock = None
        self._connect()

    def _connect(self):
        if self.tcp:
            self.sock = socket.create_connection(_hostport(self.tcp), timeout=5)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if self.mesh:
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    def send(self, xml: str, chat=False):
        data = xml.encode("utf-8")
        if self.verbose:
            print(xml[:160] + ("..." if len(xml) > 160 else ""))
        if self.tcp:
            try:
                self.sock.sendall(data)
            except OSError:
                self._connect()
                self.sock.sendall(data)
        elif self.udp:
            self.sock.sendto(data, _hostport(self.udp))
        else:
            self.sock.sendto(data, MESH_CHAT if chat else MESH_SA)

    def close(self):
        if self.sock:
            self.sock.close()


# ---------------------------------------------------------------- objects
def zone_xml(z, on=True):
    if z["kind"] == "radar":
        stroke, fill = cot.COLORS["radar"]
        label = f'{z["callsign"]} (radar)'
    elif z["side"] == "enemy":
        stroke, fill = cot.COLORS["enemy"]
        label = f'{z["callsign"]} (enemy EW)'
    else:
        stroke, fill = cot.COLORS["jammer_on" if on else "jammer_off"]
        label = f'{z["callsign"]} {"ON" if on else "OFF"}'
    remarks = f'SPECTRUM-SYNC footprint, bands {",".join(z.get("bands", []))}' if z["kind"] == "jammer" else "detection radius"
    return cot.shape(f'spectrum-sync.zone.{z["id"]}', label, z["polygon"], stroke, fill, True, remarks)


def route_xml(result, mode, uid_suffix=None):
    r = result["routes"][mode]
    stroke, _ = cot.COLORS["baseline" if mode == "baseline" else "route"]
    pts = [(p["lat"], p["lon"]) for p in r["waypoints"]]
    label = f'{result["scenario"]["drone"].get("callsign", "UAV")} {mode} {r["battery_pct"]:.0f}%'
    remarks = f'{r["distance_m"]/1000:.1f} km, {r["duration_s"]/60:.1f} min, hover {r["wait_s"]:.0f}s'
    return cot.shape(f'spectrum-sync.route.{uid_suffix or mode}', label, pts, stroke, 0, False, remarks,
                     weight=4.0 if mode != "baseline" else 2.0)


def static_objects(result, sc: Scenario, routes=("recommended", "baseline")):
    out = [cot.bot_presence(sc.pilot["lat"], sc.pilot["lon"])]
    for z in result["zones"]:
        on = True
        if z["kind"] == "jammer":
            j = next(j for j in sc.jammers if j["id"] == z["id"])
            on = sc.jammer_on_raw(j, 0.0)
        out.append(zone_xml(z, on))
        if z["kind"] == "jammer":
            typ = "a-f-G-U-C" if z["side"] == "friendly" else "a-h-G"
            out.append(cot.marker(f'spectrum-sync.jammer.{z["id"]}', z["callsign"], z["lat"], z["lon"], typ,
                                  f'jammer, bands {",".join(z["bands"])}'))
    s = result["scenario"]
    out.append(cot.marker("spectrum-sync.pilot", s["pilot"]["callsign"] or "PILOT", s["pilot"]["lat"], s["pilot"]["lon"], "a-f-G-U-C"))
    out.append(cot.marker("spectrum-sync.target", s["target"]["callsign"] or "TARGET", s["target"]["lat"], s["target"]["lon"], "a-h-G"))
    for name in routes:
        mode = result["recommended"] if name == "recommended" else name
        if mode and result["routes"][mode].get("feasible"):
            out.append(route_xml(result, mode, "main" if name == "recommended" else None))
    return out


def chat_text(e):
    to = e["to"]
    prefix = "[PILOT] " if to == "pilot" else (f"[EW {to[3:]}] " if to.startswith("ew:") else "[ALL] ")
    return prefix + e["text"]


# ---------------------------------------------------------------- commands
def cmd_test(sender: Sender, lat: float, lon: float):
    """One-evening integration test: one polygon + one chat message."""
    sender.send(cot.bot_presence(lat, lon))
    d = 0.004
    square = [(lat + d, lon - d), (lat + d, lon + d), (lat - d, lon + d), (lat - d, lon - d)]
    s, f = cot.COLORS["jammer_on"]
    sender.send(cot.shape("spectrum-sync.test.zone", "SPECTRUM-SYNC TEST ZONE", square, s, f, True, "test"))
    sender.send(cot.geochat("SPECTRUM-SYNC test message. If you can read this, TAK integration works.",
                            f"test{int(time.time())}"), chat=True)
    print(f"sent presence + test zone at {lat:.5f},{lon:.5f} + chat message")


def cmd_push(sender: Sender, result: dict, sc: Scenario, with_chat=True):
    objs = static_objects(result, sc)
    for x in objs:
        sender.send(x)
    n_chat = 0
    if with_chat:
        rec = result["recommended"]
        depart = result["routes"][rec]["depart_s"] if rec else 0.0
        for i, e in enumerate(ev for ev in result["events"] if ev["t_s"] <= depart):
            sender.send(cot.geochat(chat_text(e), f"push{int(time.time())}-{i}"), chat=True)
            n_chat += 1
    print(f"pushed {len(objs)} objects, {n_chat} chat messages")


def cmd_clear(sender: Sender, result: dict):
    uids = [f'spectrum-sync.zone.{z["id"]}' for z in result["zones"]]
    uids += [f'spectrum-sync.jammer.{z["id"]}' for z in result["zones"] if z["kind"] == "jammer"]
    uids += ["spectrum-sync.pilot", "spectrum-sync.target", "spectrum-sync.uav", "spectrum-sync.route.main",
             "spectrum-sync.test.zone"] + [f"spectrum-sync.route.{m}" for m in result["routes"]]
    for u in uids:
        sender.send(cot.delete(u))
    print(f"sent delete for {len(uids)} objects")


def cmd_live(sender: Sender, result: dict, sc: Scenario, mode=None, accel=10.0, tick=1.0):
    """Play the mission: drone moves along the route, zones change colour with the schedule,
    timed notifications go to GeoChat. Scenario time runs `accel` times faster than real time."""
    mode = mode or result["recommended"]
    r = result["routes"][mode]
    if not r.get("feasible"):
        raise SystemExit(f"route '{mode}' not feasible: {r.get('reason')}")
    for x in static_objects(result, sc, routes=(mode, "baseline") if mode != "baseline" else ("baseline",)):
        sender.send(x)
    pts = r["points"]
    zones = {z["id"]: z for z in result["zones"] if z["kind"] == "jammer"}
    state = {j["id"]: sc.jammer_on_raw(j, r["depart_s"]) for j in sc.jammers}
    events = [e for e in result["events"]]
    sent = set()
    uav = result["scenario"]["drone"].get("callsign", "UAV")
    alt = float(result["scenario"]["drone"].get("altitude_m", 80))
    t0_wall = time.time()
    t_s = r["depart_s"]
    print(f"live playback of '{mode}' route, x{accel:g} speed, {r['duration_s']/accel:.0f}s wall time")
    while True:
        t_s = r["depart_s"] + (time.time() - t0_wall) * accel
        # jammer state changes
        for j in sc.jammers:
            on = sc.jammer_on_raw(j, t_s)
            if on != state[j["id"]]:
                state[j["id"]] = on
                sender.send(zone_xml(zones[j["id"]], on))
                print(f"  {sc.hms(t_s)} {j['id']} -> {'ON' if on else 'OFF'}")
        # notifications
        for i, e in enumerate(events):
            if i not in sent and e["t_s"] <= t_s:
                sent.add(i)
                sender.send(cot.geochat(chat_text(e), f"live{int(t0_wall)}-{i}"), chat=True)
                print(f"  {sc.hms(e['t_s'])} chat: {chat_text(e)}")
        # drone position
        lat, lon, course = _interp(pts, min(t_s, pts[-1]["t_s"]))
        speed = 0.0 if t_s >= pts[-1]["t_s"] else float(result["scenario"]["drone"]["speed_mps"])
        sender.send(cot.drone("spectrum-sync.uav", uav, lat, lon, alt, course, speed))
        if t_s >= pts[-1]["t_s"] and len(sent) == len(events):
            break
        time.sleep(tick)
    sender.send(cot.bot_presence(sc.pilot["lat"], sc.pilot["lon"]))
    print("done")


def _interp(pts, t):
    for a, b in zip(pts, pts[1:]):
        if a["t_s"] <= t <= b["t_s"]:
            f = 0.0 if b["t_s"] == a["t_s"] else (t - a["t_s"]) / (b["t_s"] - a["t_s"])
            lat = a["lat"] + f * (b["lat"] - a["lat"])
            lon = a["lon"] + f * (b["lon"] - a["lon"])
            course = math.degrees(math.atan2(b["x"] - a["x"], b["y"] - a["y"])) % 360
            return lat, lon, course
    p = pts[-1] if t >= pts[-1]["t_s"] else pts[0]
    return p["lat"], p["lon"], 0.0
