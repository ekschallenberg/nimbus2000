import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import tracker as t  # noqa: E402

CITIES = [
    {"key": "aa", "name": "Alpha, AA", "lat": "1", "lon": "2"},
    {"key": "bb", "name": "Beta", "lat": "3", "lon": "4"},
    {"key": "cc", "name": "Gamma", "lat": "5", "lon": "6"},
]


def weather_payload(temps, humid=50):
    return [{"latitude": 0, "longitude": 0,
             "current": {"time": "2026-01-01T06:00", "temperature_2m": x,
                         "relative_humidity_2m": humid, "wind_speed_10m": 5.5,
                         "precipitation": 0.0, "pressure_msl": 1010.5}} for x in temps]


def aq_payload(aqis):
    return [{"latitude": 0, "longitude": 0,
             "current": {"time": "2026-01-01T06:00", "us_aqi": a, "pm2_5": 1.5,
                         "pm10": 2.5, "ozone": 30.0}} for a in aqis]


def make_getter(temps=(10, 20, 30), aqis=(40, 50, 60), fail=()):
    """A fake http getter keyed on the URL; `fail` = source names that error."""
    def getter(url):
        name = "weather" if "api.open-meteo" in url and "air-quality" not in url else "air_quality"
        if name in fail:
            raise RuntimeError("boom")
        payload = weather_payload(temps) if name == "weather" else aq_payload(aqis)
        return json.dumps(payload).encode()
    return getter


@pytest.fixture
def cities():
    return [dict(c) for c in CITIES]


@pytest.fixture
def dirs(tmp_path):
    return {"raw_dir": str(tmp_path / "raw"),
            "history_path": str(tmp_path / "history.csv"),
            "status_path": str(tmp_path / "status.json")}


@pytest.fixture(autouse=True)
def small_threshold(monkeypatch):
    """Fixtures have 3 cities; the real rule (10) is tested explicitly."""
    monkeypatch.setattr(t, "MIN_CITIES", 1)
