"""Unit tests for backend horizon graph service (horizon_graph.py)."""

import datetime

from astroweather import horizon_graph as module


class FakeAngle:
    def __init__(self, value):
        self.value = value

    def to_value(self, _unit):
        return self.value


class FakeCoord:
    def __init__(self, alt=10.04, az=120.06):
        self.alt = FakeAngle(alt)
        self.az = FakeAngle(az)

    def transform_to(self, _frame):
        return self


def test_coord_attribute_with_to_value_and_float_paths():
    svc = module.HorizonGraphService(45.0, -73.0, "UTC")

    coord = type("Coord", (), {"alt": FakeAngle(12.34), "az": 56.78})()
    assert svc._coord_attribute(coord, "alt") == 12.34
    assert svc._coord_attribute(coord, "az") == 56.78


def test_coord_attribute_returns_none_for_missing_or_bad_values():
    svc = module.HorizonGraphService(45.0, -73.0, "UTC")

    class BadAngle:
        def to_value(self, _unit):
            raise TypeError("bad")

    coord = type("Coord", (), {"alt": BadAngle()})()
    assert svc._coord_attribute(coord, "missing") is None
    assert svc._coord_attribute(coord, "alt") is None


def test_generate_body_positions_sun_and_moon(monkeypatch):
    svc = module.HorizonGraphService(45.0, -73.0, "UTC")

    monkeypatch.setattr(module, "AstroTime", lambda dt: dt)
    monkeypatch.setattr(module, "AltAz", lambda **_kwargs: object())
    monkeypatch.setattr(module, "get_sun", lambda _t: FakeCoord(alt=1.23, az=45.67))
    monkeypatch.setattr(module, "get_body", lambda _name, _t, _loc: FakeCoord(alt=2.34, az=67.89))

    date = datetime.date(2026, 3, 11)
    sun_points = svc._generate_body_positions(date, "sun")
    moon_points = svc._generate_body_positions(date, "moon")

    assert len(sun_points) == 25
    assert len(moon_points) == 25
    assert sun_points[0].time == "00:00"
    assert sun_points[-1].time == "24:00"
    assert sun_points[0].altitude_deg == 1.2
    assert moon_points[0].azimuth_deg == 67.9


def test_generate_body_positions_unknown_body_returns_empty():
    svc = module.HorizonGraphService(45.0, -73.0, "UTC")
    points = svc._generate_body_positions(datetime.date(2026, 3, 11), "planetx")
    assert points == []


def test_get_horizon_data_uses_local_date(monkeypatch):
    svc = module.HorizonGraphService(45.0, -73.0, "UTC")

    fixed_now = datetime.datetime(2026, 3, 11, 18, 0, tzinfo=datetime.timezone.utc)

    class FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now

    monkeypatch.setattr(module.datetime, "datetime", FakeDateTime)
    monkeypatch.setattr(svc, "_generate_body_positions", lambda _date, body: [body])

    data = svc.get_horizon_data()

    assert data.date == "2026-03-11"
    assert data.sun_data == ["sun"]
    assert data.moon_data == ["moon"]
