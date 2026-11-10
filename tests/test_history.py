import csv
import gzip
import json
import os
from datetime import datetime, timezone

import fetch
import tracker as t
from conftest import make_getter


def run(date, cities, dirs, **kw):
    now = datetime.fromisoformat(date).replace(hour=6, minute=15, tzinfo=timezone.utc)
    return fetch.run(date, cities, now=now, getter=make_getter(**kw), **dirs)


def hist(dirs):
    with open(dirs["history_path"], newline="") as fh:
        return list(csv.DictReader(fh))


def test_first_run_writes_raw_files_and_history(cities, dirs):
    ok, st = run("2026-01-01", cities, dirs)
    assert ok
    day = os.path.join(dirs["raw_dir"], "2026-01-01")
    assert sorted(os.listdir(day)) == ["air_quality.json.gz", "cities.csv.gz", "weather.json.gz"]
    assert json.loads(gzip.open(os.path.join(day, "weather.json.gz")).read())[0]["current"]
    rows = hist(dirs)
    assert len(rows) == 3
    assert list(rows[0]) == t.COLUMNS
    assert st["items"] == 3 and st["days_with_success"] == 1
    assert st["first_run_date"] == "2026-01-01"
    assert st["sources"] == [{"name": "weather", "ok": True, "count": 3},
                             {"name": "air_quality", "ok": True, "count": 3}]


def test_second_run_same_day_does_not_duplicate(cities, dirs):
    run("2026-01-01", cities, dirs, temps=(10, 20, 30))
    run("2026-01-01", cities, dirs, temps=(11, 21, 31))  # replaces that day
    rows = hist(dirs)
    assert len(rows) == 3
    assert [r["temperature_2m"] for r in rows] == ["11", "21", "31"]
    st = json.load(open(dirs["status_path"]))
    assert st["days_with_success"] == 1


def test_rows_sorted_by_date_then_item_id(cities, dirs):
    run("2026-01-02", list(reversed(cities)), dirs)
    run("2026-01-01", cities, dirs)
    rows = hist(dirs)
    keys = [(r["date"], r["item_id"]) for r in rows]
    assert keys == sorted(keys) and len(rows) == 6


def test_build_is_reproducible_from_raw_only(cities, dirs):
    run("2026-01-01", cities, dirs)
    run("2026-01-02", cities, dirs, temps=(1, 2, 3))
    first = open(dirs["history_path"]).read()
    os.remove(dirs["history_path"])
    # rebuild with a *different* cities list: raw snapshot must win
    t.build_history(dirs["raw_dir"], dirs["history_path"],
                    fallback_cities=[{"key": "zz", "name": "Z", "lat": "0", "lon": "0"}])
    assert open(dirs["history_path"]).read() == first


def test_failed_source_writes_no_raw_file_and_run_survives(cities, dirs):
    ok, st = run("2026-01-01", cities, dirs, fail=("air_quality",))
    assert not ok  # -> non-zero exit
    day = os.listdir(os.path.join(dirs["raw_dir"], "2026-01-01"))
    assert "air_quality.json.gz" not in day and "weather.json.gz" in day
    rows = hist(dirs)
    assert len(rows) == 3 and rows[0]["us_aqi"] == "" and rows[0]["temperature_2m"] == "10"
    assert {"name": "air_quality", "ok": False, "count": 0} in st["sources"]


def test_all_sources_failed_still_finishes(cities, dirs):
    ok, st = run("2026-01-01", cities, dirs, fail=("weather", "air_quality"))
    assert not ok and st["days_with_success"] == 0 and st["items"] == 0
    assert hist(dirs) == []
    assert all(not s["ok"] for s in st["sources"])


def test_wrong_result_count_is_a_failed_source(cities, dirs):
    bad = lambda url: json.dumps([{"current": {"temperature_2m": 1}}]).encode()  # noqa: E731
    ok, st = fetch.run("2026-01-01", cities, getter=bad, **dirs)
    assert not ok and all(not s["ok"] for s in st["sources"])


def test_fewer_than_ten_cities_with_data_is_an_error(cities, dirs, monkeypatch):
    monkeypatch.setattr(t, "MIN_CITIES", 10)
    ok, st = run("2026-01-01", cities, dirs)  # only 3 cities < MIN_CITIES
    assert not ok  # raw files are still kept
    assert st["sources"][0]["count"] == 3
    assert len(hist(dirs)) == 3


def test_ten_cities_is_enough(dirs, monkeypatch):
    monkeypatch.setattr(t, "MIN_CITIES", 10)
    many = [{"key": "c%02d" % i, "name": "C%d" % i, "lat": "0", "lon": str(i)} for i in range(12)]
    ok, st = run("2026-01-01", many, dirs, temps=tuple(range(12)), aqis=tuple(range(12)))
    assert ok and st["items"] == 12


def test_new_and_gone_in_status(cities, dirs):
    run("2026-01-01", cities, dirs)
    run("2026-01-02", cities[:2], dirs, temps=(1, 2), aqis=(1, 2))
    st = json.load(open(dirs["status_path"]))
    assert st["gone_today"] == ["cc"] and st["new_today"] == [] and st["items"] == 2


def test_missing_cities_snapshot_falls_back(cities, dirs):
    run("2026-01-01", cities, dirs)
    os.remove(os.path.join(dirs["raw_dir"], "2026-01-01", t.CITIES_SNAPSHOT))
    rows = t.build_history(dirs["raw_dir"], dirs["history_path"], fallback_cities=cities)
    assert len(rows) == 3


def test_http_get_retries_with_backoff():
    calls, waits = [], []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def opener(req, timeout):
        calls.append((req.get_header("User-agent"), timeout))
        if len(calls) < 3:
            raise OSError("reset")
        return Resp()

    assert fetch.http_get("http://x", sleep=waits.append, opener=opener) == b"{}"
    assert waits == [2, 4] and calls[0][0] and calls[0][1] == fetch.TIMEOUT


def test_http_get_gives_up_after_three_retries():
    import pytest
    n = []

    def opener(req, timeout):
        n.append(1)
        raise OSError("down")

    with pytest.raises(RuntimeError):
        fetch.http_get("http://x", sleep=lambda s: None, opener=opener)
    assert len(n) == 4  # first try + 3 retries


def test_request_url_has_all_cities_in_one_request(cities):
    url = fetch.build_url("weather", cities)
    assert "latitude=1,3,5" in url and "longitude=2,4,6" in url
    assert "timezone=UTC" in url and "pressure_msl" in url
    assert "air-quality-api" in fetch.build_url("air_quality", cities)
