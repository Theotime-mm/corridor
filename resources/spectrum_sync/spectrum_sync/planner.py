"""4D (x, y, t) route planner.

Search: A* over (cell, time). Moves = 8 neighbours + hover-in-place.
Cost  = energy (J): cruise power while moving, hover power while waiting.
A cell is forbidden at time t if, with the jammers active at t:
  - C2 uplink (receiver = drone):    J/S > js_crit  or  S < sensitivity
  - video downlink (receiver = pilot): J/S > js_crit or  S < sensitivity
  - inside a radar detection radius
"""
import heapq
import math

import numpy as np

from . import rf
from .scenario import MODES, Scenario

NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
GROUND_ANTENNA_M = 2.0


class Planner:
    def __init__(self, sc: Scenario):
        self.sc = sc
        g = sc.grid
        self.cell = float(g["cell_m"])
        self.x0, self.y0 = float(g["x0"]), float(g["y0"])
        self.nx = int(round(g["width_m"] / self.cell))
        self.ny = int(round(g["height_m"] / self.cell))
        xs = self.x0 + (np.arange(self.nx) + 0.5) * self.cell
        ys = self.y0 + (np.arange(self.ny) + 0.5) * self.cell
        self.X, self.Y = np.meshgrid(xs, ys)          # shape (ny, nx)
        self.alt = float(sc.drone.get("altitude_m", 80.0))
        self._mask_cache = {}
        self._precompute()

    # ------------------------------------------------------------------ RF
    def _pl(self, d, band):
        p = self.sc.prop
        return rf.path_loss_db(d, rf.band_mhz(band), p.get("exponent", 2.5), p.get("breakpoint_m", 100.0))

    def _d3(self, x, y):
        return np.sqrt((self.X - x) ** 2 + (self.Y - y) ** 2 + (self.alt - GROUND_ANTENNA_M) ** 2)

    def _precompute(self):
        sc, dr = self.sc, self.sc.drone
        self.c2 = dr.get("c2")
        self.video = dr.get("video")
        d_pilot = self._d3(sc.pilot["x"], sc.pilot["y"])
        static = np.zeros_like(self.X, dtype=bool)

        if self.c2:
            self.S_c2 = self.c2["pilot_eirp_dbm"] - self._pl(d_pilot, self.c2["band"])
            static |= self.S_c2 < self.c2.get("sensitivity_dbm", -110.0)
        if self.video:
            self.S_vid = self.video["drone_eirp_dbm"] - self._pl(d_pilot, self.video["band"])
            static |= self.S_vid < self.video.get("sensitivity_dbm", -95.0)
        for r in sc.radars:
            static |= np.hypot(self.X - r["x"], self.Y - r["y"]) <= r["radius_m"]
        self.static_bad = static

        # Per-jammer received power: at the drone (C2) and at the pilot (video)
        self.J_c2, self.J_vid = {}, {}
        for j in sc.jammers:
            if self.c2 and self.c2["band"] in j["bands"]:
                d = self._d3(j["x"], j["y"])
                g = rf.antenna_gain_db(j["antenna"], self.X - j["x"], self.Y - j["y"])
                self.J_c2[j["id"]] = j["eirp_dbm"] + g - self._pl(d, self.c2["band"])
            if self.video and self.video["band"] in j["bands"]:
                dx, dy = sc.pilot["x"] - j["x"], sc.pilot["y"] - j["y"]
                d = math.sqrt(dx * dx + dy * dy)
                g = float(rf.antenna_gain_db(j["antenna"], np.array(dx), np.array(dy)))
                self.J_vid[j["id"]] = j["eirp_dbm"] + g - float(self._pl(np.array(d), self.video["band"]))

    def _link_bad(self, active_ids):
        bad = np.zeros_like(self.X, dtype=bool)
        jc = [self.J_c2[i] for i in active_ids if i in self.J_c2]
        if jc:
            bad |= (rf.db_sum(jc) - self.S_c2) > self.c2["js_crit_db"]
        jv = [self.J_vid[i] for i in active_ids if i in self.J_vid]
        if jv:
            bad |= (rf.db_sum(jv) - self.S_vid) > self.video["js_crit_db"]
        return bad

    def jammer_footprint(self, jid):
        """Cells where this jammer ALONE breaks a link (depends on pilot position)."""
        return self._link_bad([jid])

    def display_footprint(self, jid):
        """What to draw for a jammer. Friendly: cells blocked BECAUSE it is on, with every other
        jammer on too (powers add up, so this includes the corridors it closes together with
        others). Enemy: its own footprint."""
        j = next(j for j in self.sc.jammers if j["id"] == jid)
        if j["side"] != "friendly":
            return self._link_bad([jid])
        all_ids = [x["id"] for x in self.sc.jammers]
        others = [i for i in all_ids if i != jid]
        return self._link_bad(all_ids) & ~self._link_bad(others)

    def active_set(self, t, mode):
        return frozenset(j["id"] for j in self.sc.jammers if self.sc.jammer_on(j, t, mode))

    def forbidden(self, active):
        m = self._mask_cache.get(active)
        if m is None:
            m = self.static_bad | self._link_bad(active)
            self._mask_cache[active] = m
        return m

    # --------------------------------------------------------------- grid
    def cell_of(self, x, y):
        ix = int((x - self.x0) // self.cell)
        iy = int((y - self.y0) // self.cell)
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            raise ValueError(f"point ({x:.0f},{y:.0f}) outside planning grid")
        return ix, iy

    def center(self, ix, iy):
        return self.x0 + (ix + 0.5) * self.cell, self.y0 + (iy + 0.5) * self.cell

    # --------------------------------------------------------------- SIPP
    def _segments(self, mode, depart_s, horizon):
        """Split time at schedule breakpoints; the forbidden mask is constant on each segment."""
        bps = [b for b in self.sc.breakpoints() if depart_s < b < horizon]
        edges = [depart_s] + bps + [horizon]
        masks = [self.forbidden(self.active_set((a + b) / 2, mode)) for a, b in zip(edges, edges[1:])]
        return edges, np.stack(masks)

    def plan(self, mode="safe", depart_s=0.0):
        """Safe-Interval Path Planning (SIPP): state = (cell, safe interval of that cell).
        Hovering is implicit: from a cell you may leave at any time inside its safe interval.
        g = arrival time (time-optimal); energy is computed on the resulting route."""
        assert mode in MODES
        sc, dr, P = self.sc, self.sc.drone, self.sc.planning
        v = float(dr["speed_mps"])
        max_s = float(P["max_mission_s"])
        horizon = depart_s + max_s
        start = self.cell_of(sc.launch["x"], sc.launch["y"])
        goal = self.cell_of(sc.target["x"], sc.target["y"])
        edges, F = self._segments(mode, depart_s, horizon)
        nseg = len(edges) - 1
        cache = {}

        def intervals(ix, iy):
            key = (ix, iy)
            iv = cache.get(key)
            if iv is None:
                col = F[:, iy, ix]
                iv, k = [], 0
                while k < nseg:
                    if not col[k]:
                        s = k
                        while k + 1 < nseg and not col[k + 1]:
                            k += 1
                        iv.append((edges[s], edges[k + 1]))
                    k += 1
                cache[key] = iv
            return iv

        def h(ix, iy):
            dx, dy = abs(ix - goal[0]), abs(iy - goal[1])
            return (max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)) * self.cell / v

        iv0 = intervals(*start)
        if not iv0 or iv0[0][0] > depart_s:
            return self._fail(mode, "launch point is jammed / forbidden at departure")

        moves = [(dx, dy, self.cell * math.hypot(dx, dy) / v) for dx, dy in NEIGHBOURS]
        k0 = (start[0], start[1], 0)
        parent = {k0: None}              # key -> (parent_key, depart_tau, arrive_t)
        best = {k0: depart_s}
        heap = [(depart_s + h(*start), depart_s, start[0], start[1], 0)]
        closed = set()
        expanded = 0
        while heap:
            f, t, ix, iy, idx = heapq.heappop(heap)
            key = (ix, iy, idx)
            if key in closed:
                continue
            closed.add(key)
            expanded += 1
            if (ix, iy) == goal:
                return self._build(mode, parent, key, depart_s, expanded)
            b = intervals(ix, iy)[idx][1]
            for dx, dy, d in moves:
                nx_, ny_ = ix + dx, iy + dy
                if not (0 <= nx_ < self.nx and 0 <= ny_ < self.ny):
                    continue
                for j, (a2, b2) in enumerate(intervals(nx_, ny_)):
                    if a2 - d >= b:
                        break
                    tau = max(t, a2 - d)            # earliest departure that lands inside (a2, b2)
                    arr = tau + d
                    if tau >= b or arr >= b2 or arr > horizon:
                        continue
                    k2 = (nx_, ny_, j)
                    if k2 in closed or arr >= best.get(k2, math.inf):
                        continue
                    best[k2] = arr
                    parent[k2] = (key, tau, arr)
                    heapq.heappush(heap, (arr + h(nx_, ny_), arr, nx_, ny_, j))
        return self._fail(mode, "no route within max_mission_s (target unreachable)")

    # ------------------------------------------------------------ output
    def _fail(self, mode, reason):
        return {"mode": mode, "feasible": False, "reason": reason}

    def _build(self, mode, parent, key, depart_s, expanded):
        sc, dr = self.sc, self.sc.drone
        steps = []
        while parent[key] is not None:
            pk, tau, arr = parent[key]
            steps.append((pk, key, tau, arr))
            key = pk
        steps.reverse()
        p_cruise, p_hover = float(dr["cruise_power_w"]), float(dr["hover_power_w"])

        def mk(t, k):
            x, y = self.center(k[0], k[1])
            lat, lon = sc.frame.to_latlon(x, y)
            return {"t_s": round(t, 1), "time": sc.hms(t), "x": round(x, 1), "y": round(y, 1),
                    "lat": round(lat, 7), "lon": round(lon, 7)}

        pts = [mk(depart_s, key)]
        t_prev, dist, wait, joules = depart_s, 0.0, 0.0, 0.0
        for pk, k, tau, arr in steps:
            if tau > t_prev + 1e-6:                    # hover before this move
                wait += tau - t_prev
                joules += (tau - t_prev) * p_hover
                pts.append(mk(tau, pk))
            joules += (arr - tau) * p_cruise
            dist += self.cell * math.hypot(k[0] - pk[0], k[1] - pk[1])
            pts.append(mk(arr, k))
            t_prev = arr
        energy_wh = joules / 3600.0
        pct = 100.0 * energy_wh / dr["battery_wh"]
        reserve = dr.get("reserve_pct", 20.0)
        return {
            "mode": mode, "feasible": True,
            "depart_s": depart_s, "arrive_s": round(t_prev, 1),
            "duration_s": round(t_prev - depart_s, 1),
            "distance_m": round(dist), "wait_s": round(wait, 1),
            "energy_wh": round(energy_wh, 2), "battery_pct": round(pct, 1),
            "battery_ok": pct <= 100.0 - reserve,
            "points": pts, "waypoints": compress(pts),
            "crossings": self.crossings(pts, mode),
            "expanded_nodes": expanded,
        }

    def crossings(self, pts, mode):
        """Segments of the route that are only clear because a friendly jammer is cut:
        the point would be forbidden if that jammer were ON, given the others' state at that time."""
        out = []
        for j in self.sc.jammers:
            if j["side"] != "friendly" or not j["schedule"]["off_windows"]:
                continue
            relies = []
            for p in pts:
                act = self.active_set(p["t_s"], mode)
                if j["id"] in act:
                    relies.append(False)
                    continue
                ix, iy = self.cell_of(p["x"], p["y"])
                relies.append(bool(self.forbidden(act | {j["id"]})[iy, ix]))
            i = 0
            while i < len(pts):
                if not relies[i]:
                    i += 1
                    continue
                k = i
                while k + 1 < len(pts) and relies[k + 1]:
                    k += 1
                t_in, t_out = pts[i]["t_s"], pts[k]["t_s"]
                win = next((w for w in j["schedule"]["off_windows"]
                            if w["start_s"] <= t_in and t_out <= w["end_s"]), None)
                out.append({
                    "jammer": j["id"], "callsign": j.get("callsign", j["id"]),
                    "enter_s": t_in, "exit_s": t_out,
                    "enter": self.sc.hms(t_in), "exit": self.sc.hms(t_out),
                    "window": None if win is None else {
                        "start_s": win["start_s"], "end_s": win["end_s"],
                        "start": self.sc.hms(win["start_s"]), "end": self.sc.hms(win["end_s"]),
                        "confirmed": win["confirmed"]},
                })
                i = k + 1
        return out

    # ------------------------------------------------------------- zones
    def footprint_polygon(self, jid, n_rays=72):
        """Star-shaped outline of a jammer footprint (ray casting from the jammer)."""
        j = next(j for j in self.sc.jammers if j["id"] == jid)
        fp = self.display_footprint(jid)
        rmax = math.hypot(self.nx, self.ny) * self.cell
        if j["side"] == "friendly":
            # cap at 2.5x its stand-alone reach: keeps the corridor it closes, drops thin edge slivers
            alone = self.jammer_footprint(jid)
            if alone.any():
                reach = np.hypot(self.X[alone] - j["x"], self.Y[alone] - j["y"]).max()
                rmax = min(rmax, 2.5 * reach)
        poly = []
        for k in range(n_rays):
            a = 2 * math.pi * k / n_rays
            r, step, last_in = 0.0, self.cell / 2, 0.0
            while r < rmax:
                x, y = j["x"] + r * math.sin(a), j["y"] + r * math.cos(a)
                try:
                    ix, iy = self.cell_of(x, y)
                except ValueError:
                    break
                if fp[iy, ix]:
                    last_in = r
                elif r - last_in > 3 * self.cell:
                    break
                r += step
            x, y = j["x"] + last_in * math.sin(a), j["y"] + last_in * math.cos(a)
            poly.append(self.sc.frame.to_latlon(x, y))
        return poly

    def zones(self):
        sc = self.sc
        out = []
        for j in sc.jammers:
            out.append({
                "kind": "jammer", "id": j["id"], "callsign": j.get("callsign", j["id"]),
                "side": j["side"], "bands": j["bands"], "lat": j["lat"], "lon": j["lon"],
                "polygon": [[round(a, 7), round(b, 7)] for a, b in self.footprint_polygon(j["id"])],
                "schedule": j["schedule"],
            })
        for r in sc.radars:
            poly = []
            for k in range(48):
                a = 2 * math.pi * k / 48
                poly.append(sc.frame.to_latlon(r["x"] + r["radius_m"] * math.sin(a),
                                               r["y"] + r["radius_m"] * math.cos(a)))
            out.append({"kind": "radar", "id": r["id"], "callsign": r.get("callsign", r["id"]),
                        "side": "enemy", "lat": r["lat"], "lon": r["lon"], "radius_m": r["radius_m"],
                        "polygon": [[round(a, 7), round(b, 7)] for a, b in poly]})
        return out


def compress(pts):
    """Keep only turning points and hover segments."""
    if len(pts) <= 2:
        return pts
    keep = [pts[0]]
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        d1 = (b["x"] - a["x"], b["y"] - a["y"])
        d2 = (c["x"] - b["x"], c["y"] - b["y"])
        if d1 != d2:
            keep.append(b)
    keep.append(pts[-1])
    return keep
