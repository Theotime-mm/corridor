"""Local flat-earth frame: metres east/north of an origin <-> WGS84 lat/lon.
Good to a few metres over a 20 km area, which is all the demo needs."""
import math

R_EARTH = 6371000.0


class LocalFrame:
    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self._kx = math.radians(1) * R_EARTH * math.cos(math.radians(lat0))
        self._ky = math.radians(1) * R_EARTH

    def to_xy(self, lat: float, lon: float):
        return (lon - self.lon0) * self._kx, (lat - self.lat0) * self._ky

    def to_latlon(self, x: float, y: float):
        return self.lat0 + y / self._ky, self.lon0 + x / self._kx
