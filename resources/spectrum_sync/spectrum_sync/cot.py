"""Cursor-on-Target (CoT) XML builders for ATAK / WinTAK / iTAK.

Shapes use the ATAK drawing type `u-d-f` (freehand polyline; closed when the first point
is repeated at the end). Colours are ARGB packed into a signed 32-bit int, as ATAK expects."""
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape, quoteattr

BOT_UID = "SPECTRUM-SYNC-BOT"
BOT_CALLSIGN = "SPECTRUM-SYNC"
NO_HAE = 'hae="9999999.0" ce="9999999.0" le="9999999.0"'


def argb(a, r, g, b):
    v = (a << 24) | (r << 16) | (g << 8) | b
    return v - (1 << 32) if v >= (1 << 31) else v


COLORS = {
    "jammer_on": (argb(255, 230, 30, 30), argb(70, 230, 30, 30)),
    "jammer_off": (argb(255, 40, 200, 80), argb(25, 40, 200, 80)),
    "enemy": (argb(255, 160, 0, 160), argb(60, 160, 0, 160)),
    "radar": (argb(255, 255, 140, 0), argb(50, 255, 140, 0)),
    "route": (argb(255, 0, 200, 255), 0),
    "baseline": (argb(255, 150, 150, 150), 0),
}


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _times(stale_s: float, now: datetime = None):
    now = now or datetime.now(timezone.utc)
    return _ts(now), _ts(now), _ts(now + timedelta(seconds=stale_s))


def _event(uid, typ, lat, lon, detail, stale_s=600, how="h-e", hae=None):
    t, s, st = _times(stale_s)
    pt = (f'<point lat="{lat:.7f}" lon="{lon:.7f}" hae="{hae:.1f}" ce="10.0" le="10.0"/>' if hae is not None
          else f'<point lat="{lat:.7f}" lon="{lon:.7f}" {NO_HAE}/>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<event version="2.0" uid={quoteattr(uid)} type="{typ}" time="{t}" start="{s}" stale="{st}" how="{how}">'
            f'{pt}<detail>{detail}</detail></event>')


def bot_presence(lat, lon, stale_s=300):
    """SA message so the bot shows up as a contact (and chat messages have a sender)."""
    detail = (f'<contact callsign="{BOT_CALLSIGN}" endpoint="*:-1:stcp"/>'
              f'<__group name="Cyan" role="HQ"/>'
              f'<takv device="server" platform="SPECTRUM-SYNC" os="python" version="0.1"/>')
    return _event(BOT_UID, "a-f-G-U-C", lat, lon, detail, stale_s, how="m-g")


def shape(uid, callsign, latlons, stroke, fill=0, closed=True, remarks="", weight=3.0, stale_s=600):
    pts = list(latlons)
    if closed and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    links = "".join(f'<link point="{lat:.7f},{lon:.7f}"/>' for lat, lon in pts)
    clat = sum(p[0] for p in pts) / len(pts)
    clon = sum(p[1] for p in pts) / len(pts)
    detail = (f'{links}<strokeColor value="{stroke}"/><strokeWeight value="{weight}"/>'
              + (f'<fillColor value="{fill}"/>' if closed else "")
              + f'<contact callsign={quoteattr(callsign)}/><remarks>{escape(remarks)}</remarks>'
              f'<labels_on value="true"/>')
    return _event(uid, "u-d-f", clat, clon, detail, stale_s)


def marker(uid, callsign, lat, lon, typ="a-f-G-U-C", remarks="", stale_s=600):
    detail = f'<contact callsign={quoteattr(callsign)}/><remarks>{escape(remarks)}</remarks>'
    return _event(uid, typ, lat, lon, detail, stale_s)


def drone(uid, callsign, lat, lon, alt_m, course_deg, speed_mps, stale_s=30):
    detail = (f'<contact callsign={quoteattr(callsign)}/>'
              f'<track course="{course_deg:.1f}" speed="{speed_mps:.1f}"/>'
              f'<remarks>SPECTRUM-SYNC simulated UAV</remarks>')
    return _event(uid, "a-f-A-M-F-Q", lat, lon, detail, stale_s, how="m-g", hae=alt_m)


def geochat(text, msg_id, room="All Chat Rooms", lat=0.0, lon=0.0):
    """GeoChat message (type b-t-f) from the bot to a chat room (default: All Chat Rooms)."""
    t, s, st = _times(86400)
    uid = f"GeoChat.{BOT_UID}.{room}.{msg_id}"
    detail = (f'<__chat parent="RootContactGroup" groupOwner="false" chatroom={quoteattr(room)} '
              f'id={quoteattr(room)} senderCallsign="{BOT_CALLSIGN}">'
              f'<chatgrp uid0="{BOT_UID}" uid1={quoteattr(room)} id={quoteattr(room)}/></__chat>'
              f'<link uid="{BOT_UID}" type="a-f-G-U-C" relation="p-p"/>'
              f'<remarks source="BAO.F.ATAK.{BOT_UID}" to={quoteattr(room)} time="{t}">{escape(text)}</remarks>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<event version="2.0" uid={quoteattr(uid)} type="b-t-f" time="{t}" start="{s}" stale="{st}" how="h-g-i-g-o">'
            f'<point lat="{lat:.7f}" lon="{lon:.7f}" {NO_HAE}/><detail>{detail}</detail></event>')


def delete(uid):
    """Ask clients to remove an object (t-x-d-d tombstone)."""
    t, s, st = _times(20)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<event version="2.0" uid="{BOT_UID}.del.{escape(uid)}" type="t-x-d-d" time="{t}" start="{s}" stale="{st}" how="h-g-i-g-o">'
            f'<point lat="0" lon="0" {NO_HAE}/><detail><link uid={quoteattr(uid)} relation="none" type="none"/>'
            f'<__forcedelete/></detail></event>')
