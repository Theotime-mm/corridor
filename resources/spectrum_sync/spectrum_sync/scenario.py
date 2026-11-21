"""Scenario loading and jammer schedule logic.

Times inside the planner are seconds after scenario start_time ("t_s").
Positions may be given as {"lat", "lon"} or {"xy": [east_m, north_m]} from origin.
"""
import json
from datetime import datetime, timedelta, timezone

from .geo import LocalFrame

MODES = ("baseline", "safe", "optimistic")
# baseline   : no coordination, every friendly jammer assumed ON all the time
# safe       : only CONFIRMED off-windows are used
# optimistic : pending (unconfirmed) off-windows are used too -> needs EW confirmation


def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Scenario:
    def __init__(self, data: dict):
        self.raw = data
        self.name = data.get("name", "scenario")
        self.frame = LocalFrame(data["origin"]["lat"], data["origin"]["lon"])
        self.start_time = _parse_time(data["start_time"])
        self.grid = data["grid"]
        self.prop = data.get("propagation", {"exponent": 2.5, "breakpoint_m": 100.0})
        self.planning = {
            "enter_margin_s": 30.0, "exit_margin_s": 60.0,
            "max_mission_s": 2400.0,
            **data.get("planning", {}),
        }
        self.drone = data["drone"]
        self.pilot = self._place(data["pilot"])
        self.launch = self._place(data.get("launch", data["pilot"]))
        self.target = self._place(data["target"])
        self.jammers = [self._place(j) for j in data.get("jammers", [])]
        self.radars = [self._place(r) for r in data.get("radars", [])]
        for j in self.jammers:
            j.setdefault("side", "friendly")
            j.setdefault("antenna", {"type": "omni"})
            sch = j.setdefault("schedule", {})
            sch.setdefault("default", "on")
            for key in ("off_windows", "on_windows"):
                for w in sch.setdefault(key, []):
                    w["start_s"] = self._to_s(w, "start")
                    w["end_s"] = self._to_s(w, "end")
                    w.setdefault("confirmed", False)

    @classmethod
    def load(cls, path: str) -> "Scenario":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    # ---- helpers -------------------------------------------------------
    def _place(self, obj: dict) -> dict:
        obj = dict(obj)
        if "xy" in obj:
            obj["x"], obj["y"] = obj["xy"]
            obj["lat"], obj["lon"] = self.frame.to_latlon(obj["x"], obj["y"])
        else:
            obj["x"], obj["y"] = self.frame.to_xy(obj["lat"], obj["lon"])
        return obj

    def _to_s(self, w: dict, key: str) -> float:
        if f"{key}_s" in w:
            return float(w[f"{key}_s"])
        return (_parse_time(w[key]) - self.start_time).total_seconds()

    def abs_time(self, t_s: float) -> datetime:
        return self.start_time + timedelta(seconds=t_s)

    def hms(self, t_s: float) -> str:
        return self.abs_time(t_s).strftime("%H:%M:%S")

    # ---- schedule ------------------------------------------------------
    def jammer_on(self, j: dict, t: float, mode: str) -> bool:
        """Is jammer j considered radiating at time t, for planning in `mode`?
        Margins are applied conservatively: an off-window is shrunk, an on-window grown."""
        em, xm = self.planning["enter_margin_s"], self.planning["exit_margin_s"]
        sch = j["schedule"]
        for w in sch["on_windows"]:
            if w["start_s"] - xm <= t <= w["end_s"] + em:
                return True
        if sch["default"] == "off":
            return False
        if j["side"] != "friendly" or mode == "baseline":
            return True
        for w in sch["off_windows"]:
            if mode == "safe" and not w["confirmed"]:
                continue
            if w["start_s"] + em <= t <= w["end_s"] - xm:
                return False
        return True

    def jammer_on_raw(self, j: dict, t: float) -> bool:
        """Real (un-padded) state, for display and playback."""
        sch = j["schedule"]
        if any(w["start_s"] <= t < w["end_s"] for w in sch["on_windows"]):
            return True
        if sch["default"] == "off":
            return False
        return not any(w["start_s"] <= t < w["end_s"] for w in sch["off_windows"])

    def breakpoints(self):
        em, xm = self.planning["enter_margin_s"], self.planning["exit_margin_s"]
        pts = set()
        for j in self.jammers:
            for w in j["schedule"]["off_windows"]:
                pts |= {w["start_s"], w["end_s"], w["start_s"] + em, w["end_s"] - xm}
            for w in j["schedule"]["on_windows"]:
                pts |= {w["start_s"], w["end_s"], w["start_s"] - xm, w["end_s"] + em}
        return sorted(pts)
