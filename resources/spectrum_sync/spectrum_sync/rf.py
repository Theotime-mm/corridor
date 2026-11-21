"""RF helpers: path loss, antenna gain, dB sums. Vectorised over numpy grids.

Model: free-space loss up to a breakpoint, then log-distance with exponent n
(dual-slope, a cheap stand-in for air-to-ground LoS/NLoS behaviour)."""
import numpy as np

BAND_MHZ = {"0.4": 433.0, "0.9": 900.0, "1.2": 1260.0, "1.5": 1575.0, "2.4": 2440.0, "5.8": 5800.0}


def band_mhz(band: str) -> float:
    if band in BAND_MHZ:
        return BAND_MHZ[band]
    return float(band)  # allow raw MHz, e.g. "915"


def fspl_db(d_m, f_mhz):
    d_km = np.maximum(d_m, 1.0) / 1000.0
    return 20 * np.log10(d_km) + 20 * np.log10(f_mhz) + 32.44


def path_loss_db(d_m, f_mhz, exponent=2.5, breakpoint_m=100.0):
    d = np.maximum(d_m, 1.0)
    base = fspl_db(np.minimum(d, breakpoint_m), f_mhz)
    extra = np.where(d > breakpoint_m, 10 * exponent * np.log10(d / breakpoint_m), 0.0)
    return base + extra


def antenna_gain_db(antenna: dict, dx, dy):
    """Gain towards (dx, dy) from the antenna. omni, or sector with az/beamwidth."""
    antenna = antenna or {}
    g = antenna.get("gain_dbi", 0.0)
    if antenna.get("type", "omni") == "omni":
        return g
    az = antenna.get("azimuth_deg", 0.0)          # 0 = north, clockwise
    bw = antenna.get("beamwidth_deg", 90.0)
    fb = antenna.get("front_back_db", 20.0)
    bearing = np.degrees(np.arctan2(dx, dy)) % 360.0
    off = np.abs((bearing - az + 180.0) % 360.0 - 180.0)
    return np.where(off <= bw / 2.0, g, g - fb)


def db_sum(values):
    """Power sum of a list of dBm arrays/scalars."""
    lin = sum(10 ** (np.asarray(v) / 10.0) for v in values)
    return 10 * np.log10(lin)
