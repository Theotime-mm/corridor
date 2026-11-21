from xml.etree.ElementTree import fromstring

import pytest

from corridor.tak.cli import demo_events
from corridor.tak.cot import Framer, argb, self_sa, shape


def test_argb_is_signed_java_int() -> None:
    assert argb(255, 255, 255, 255) == -1
    assert argb(0, 0, 0, 255) == 255
    assert argb(255, 255, 0, 0) == -65536


def test_self_sa_has_contact_so_ots_registers_the_client() -> None:
    ev = fromstring(self_sa("u1", "CORRIDOR", 48.0, 11.0, 0.0))
    assert ev.get("type") == "a-f-G-U-C"
    contact = ev.find("detail/contact")
    assert contact is not None
    assert contact.get("callsign") == "CORRIDOR"


def test_closed_shape_repeats_first_vertex() -> None:
    square = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
    ev = fromstring(shape("s", "zone", square, 0.0, closed=True, stroke=-1, fill=0))
    links = [link.get("point") for link in ev.findall("detail/link")]
    assert len(links) == 5
    assert links[0] == links[-1]
    assert ev.find("detail/fillColor") is not None


def test_open_shape_keeps_vertices() -> None:
    ev = fromstring(shape("s", "line", [(0.0, 0.0), (1.0, 1.0)], 0.0, closed=False, stroke=-1))
    assert len(ev.findall("detail/link")) == 2
    assert ev.find("detail/fillColor") is None


def test_shape_needs_two_vertices() -> None:
    with pytest.raises(ValueError):
        shape("s", "x", [(0.0, 0.0)], 0.0, closed=False, stroke=-1)


def test_framer_splits_concatenated_and_partial_events() -> None:
    stream = b"".join(demo_events(48.0, 11.0, 0.0))
    stream = b'<?xml version="1.0"?>' + stream
    framer = Framer()
    first = framer.feed(stream[:100])
    rest = framer.feed(stream[100:])
    uids = [ev.get("uid") for ev in first + rest]
    assert uids == ["corridor-demo-ew-unit", "corridor-demo-jam-1", "corridor-demo-corridor-1"]
    assert framer.buffer == b""


def test_framer_skips_malformed_event() -> None:
    framer = Framer()
    good = self_sa("u1", "A", 0.0, 0.0, 0.0)
    events = framer.feed(b"<event><broken></event>" + good)
    assert [ev.get("uid") for ev in events] == ["u1"]
