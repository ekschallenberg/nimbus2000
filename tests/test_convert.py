import pytest

import tracker as t
from conftest import CITIES, aq_payload, weather_payload


def test_weather_converted_by_position(cities):
    out = t.convert_source("weather", weather_payload([1.5, 2, 3]), cities)
    assert list(out) == ["aa", "bb", "cc"]
    assert out["aa"]["temperature_2m"] == "1.5"
    assert out["bb"]["temperature_2m"] == "2"
    assert out["aa"]["pressure_msl"] == "1010.5"
    assert out["aa"]["time"] == "2026-01-01T06:00"


def test_air_quality_converted(cities):
    out = t.convert_source("air_quality", aq_payload([40, 50, 60]), cities)
    assert out["cc"]["us_aqi"] == "60"
    assert out["cc"]["pm2_5"] == "1.5"
    assert out["cc"]["ozone"] == "30.0"


def test_single_location_plain_object():
    one = [CITIES[0]]
    payload = weather_payload([7])[0]  # plain object, not a list
    out = t.convert_source("weather", payload, one)
    assert out["aa"]["temperature_2m"] == "7"


def test_count_mismatch_raises(cities):
    with pytest.raises(ValueError):
        t.convert_source("weather", weather_payload([1, 2]), cities)


def test_missing_and_null_fields_become_empty(cities):
    payload = weather_payload([1, 2, 3])
    del payload[0]["current"]["wind_speed_10m"]
    payload[1]["current"]["pressure_msl"] = None
    del payload[2]["current"]
    out = t.convert_source("weather", payload, cities)
    assert out["aa"]["wind_speed_10m"] == ""
    assert out["bb"]["pressure_msl"] == ""
    assert out["cc"]["temperature_2m"] == ""
    assert not t.has_data(out["cc"])
    assert t.count_with_data(out) == 2


def test_merge_day_combines_sources_one_row_per_city(cities):
    conv = {"weather": t.convert_source("weather", weather_payload([1, 2, 3]), cities),
            "air_quality": t.convert_source("air_quality", aq_payload([4, 5, 6]), cities)}
    rows = t.merge_day("2026-01-01", cities, conv)
    assert [r["item_id"] for r in rows] == ["aa", "bb", "cc"]
    r = rows[0]
    assert (r["item"], r["source"], r["temperature_2m"], r["us_aqi"]) == \
        ("Alpha, AA", "open-meteo", "1", "4")
    assert list(r) == t.COLUMNS


def test_merge_day_missing_source_leaves_empty_values(cities):
    conv = {"weather": t.convert_source("weather", weather_payload([1, 2, 3]), cities)}
    rows = t.merge_day("2026-01-01", cities, conv)
    assert len(rows) == 3 and rows[0]["us_aqi"] == "" and rows[0]["temperature_2m"] == "1"
