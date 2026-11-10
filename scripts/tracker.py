"""Shared logic for the weather / air-quality tracker (standard library only).

Everything that decides what ends up in data/history.csv lives here, so the
build is a pure function of the files in data/raw/.
"""
import csv
import glob
import gzip
import io
import json
import math
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CITIES_CSV = os.path.join(ROOT, "cities.csv")
RAW_DIR = os.path.join(ROOT, "data", "raw")
HISTORY_CSV = os.path.join(ROOT, "data", "history.csv")
STATUS_JSON = os.path.join(ROOT, "data", "status.json")

PROVIDER = "open-meteo"
CITIES_SNAPSHOT = "cities.csv.gz"  # copy of cities.csv used for that day's requests

# name -> url, request fields. Only these fields are requested (and so kept).
SOURCES = {
    "weather": {
        "url": "https://api.open-meteo.com/v1/forecast",
        "fields": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m",
                   "precipitation", "pressure_msl"],
        "extra": {"timezone": "UTC"},
    },
    "air_quality": {
        "url": "https://air-quality-api.open-meteo.com/v1/air-quality",
        "fields": ["us_aqi", "pm2_5", "pm10", "ozone"],
        "extra": {},
    },
}
SOURCE_FORMAT = "json"

NUMERIC = [f for s in SOURCES.values() for f in s["fields"]]
FIXED = ["date", "item_id", "item", "source"]
COLUMNS = FIXED + ["observed_at_utc"] + NUMERIC

MOVE_LIMIT = 10
MIN_CITIES = 10


# ---------------------------------------------------------------- cities
def parse_cities(text):
    cities = []
    for row in csv.DictReader(io.StringIO(text)):
        cities.append({"key": row["key"].strip(), "name": row["name"].strip(),
                       "lat": row["lat"].strip(), "lon": row["lon"].strip()})
    keys = [c["key"] for c in cities]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key in cities.csv")
    return cities


def load_cities(path=CITIES_CSV):
    with open(path, encoding="utf-8", newline="") as fh:
        return parse_cities(fh.read())


# ---------------------------------------------------------------- converting
def as_list(payload):
    """Open-Meteo returns an array for several locations, an object for one."""
    return payload if isinstance(payload, list) else [payload]


def _value(v):
    """Missing/non-numeric -> '' ; numbers keep their JSON spelling-ish form."""
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return ""
        return repr(v) if isinstance(v, float) else str(v)
    return ""


def convert_source(name, payload, cities):
    """One source's raw payload -> {item_id: {field: value, 'time': str}}.

    Results are matched to cities by position in the request order. Raises
    ValueError when the result count differs from the city count.
    """
    results = as_list(payload)
    if len(results) != len(cities):
        raise ValueError("%s: got %d results for %d cities"
                         % (name, len(results), len(cities)))
    out = {}
    for city, res in zip(cities, results):
        cur = (res or {}).get("current") or {}
        rec = {f: _value(cur.get(f)) for f in SOURCES[name]["fields"]}
        t = cur.get("time")
        rec["time"] = t if isinstance(t, str) else ""
        out[city["key"]] = rec
    return out


def has_data(rec):
    return any(rec[k] != "" for k in rec if k != "time")


def count_with_data(converted):
    return sum(1 for rec in converted.values() if has_data(rec))


def merge_day(date, cities, converted_by_source):
    """Combine the converted sources of one day into rows (one per city)."""
    rows = []
    for city in cities:
        recs = {s: c.get(city["key"]) for s, c in converted_by_source.items()}
        if not any(r and has_data(r) for r in recs.values()):
            continue
        row = {"date": date, "item_id": city["key"], "item": city["name"],
               "source": PROVIDER, "observed_at_utc": ""}
        for f in NUMERIC:
            row[f] = ""
        for s in SOURCES:  # weather first: its timestamp wins
            r = recs.get(s)
            if not r:
                continue
            for f in SOURCES[s]["fields"]:
                row[f] = r[f]
            if not row["observed_at_utc"] and r["time"]:
                row["observed_at_utc"] = r["time"]
        rows.append(row)
    return rows


# ---------------------------------------------------------------- raw files
def raw_path(raw_dir, date, source):
    return os.path.join(raw_dir, date, "%s.%s.gz" % (source, SOURCE_FORMAT))


def write_gz(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    # mtime=0 -> identical bytes for identical input (stable git diffs)
    with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(data)
    os.replace(tmp, path)


def read_gz(path):
    with gzip.open(path, "rb") as fh:
        return fh.read()


def raw_dates(raw_dir=RAW_DIR):
    if not os.path.isdir(raw_dir):
        return []
    return sorted(d for d in os.listdir(raw_dir)
                  if len(d) == 10 and os.path.isdir(os.path.join(raw_dir, d))
                  and glob.glob(os.path.join(raw_dir, d, "*.json.gz")))


def build_day(date, raw_dir=RAW_DIR, fallback_cities=None):
    """Convert one day's raw files into rows. Missing source -> no values."""
    snap = os.path.join(raw_dir, date, CITIES_SNAPSHOT)
    if os.path.exists(snap):
        cities = parse_cities(read_gz(snap).decode("utf-8"))
    else:
        cities = fallback_cities if fallback_cities is not None else load_cities()
    converted = {}
    for name in SOURCES:
        p = raw_path(raw_dir, date, name)
        if not os.path.exists(p):
            continue
        try:
            converted[name] = convert_source(name, json.loads(read_gz(p)), cities)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print("build: skipping %s %s: %s" % (date, name, exc))
    return merge_day(date, cities, converted)


def build_history(raw_dir=RAW_DIR, history_path=HISTORY_CSV, fallback_cities=None):
    """Rebuild history.csv from scratch from the raw files. Pure & repeatable."""
    rows = []
    for date in raw_dates(raw_dir):
        rows.extend(build_day(date, raw_dir, fallback_cities))
    rows.sort(key=lambda r: (r["date"], r["item_id"]))
    os.makedirs(os.path.dirname(history_path) or ".", exist_ok=True)
    with open(history_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return rows


def read_history(path=HISTORY_CSV):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------- the move rule
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def split_last_two(rows):
    """(previous_day_rows, latest_day_rows); previous is [] with <2 days."""
    dates = sorted({r["date"] for r in rows})
    if not dates:
        return [], []
    latest = [r for r in rows if r["date"] == dates[-1]]
    prev = [r for r in rows if r["date"] == dates[-2]] if len(dates) > 1 else []
    return prev, latest


def compute_moves(prev_rows, latest_rows, limit=MOVE_LIMIT):
    """The move rule.

    For every item present on both days and every numeric column with a value
    on both days:  score = |new - old| / sd, where sd is the population
    standard deviation of that column across all items on the latest day (sd
    of 0 or fewer than 2 values -> 1). The `limit` largest scores are the
    biggest moves (ties: item_id, then column). Items only on the latest day
    appeared; items only on the previous day disappeared.
    """
    prev = {r["item_id"]: r for r in prev_rows}
    cur = {r["item_id"]: r for r in latest_rows}
    sd = {}
    for col in NUMERIC:
        vals = [v for v in (_num(r.get(col)) for r in latest_rows) if v is not None]
        if len(vals) < 2:
            sd[col] = 1.0
            continue
        m = sum(vals) / len(vals)
        s = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
        sd[col] = s if s > 0 else 1.0
    moves = []
    for iid in sorted(set(prev) & set(cur)):
        for col in NUMERIC:
            old, new = _num(prev[iid].get(col)), _num(cur[iid].get(col))
            if old is None or new is None:
                continue
            moves.append({"item_id": iid, "item": cur[iid]["item"], "column": col,
                          "old": old, "new": new, "change": new - old,
                          "score": abs(new - old) / sd[col]})
    moves.sort(key=lambda m: (-m["score"], m["item_id"], m["column"]))
    return {"moves": moves[:limit],
            "appeared": sorted(set(cur) - set(prev)) if prev_rows else [],
            "gone": sorted(set(prev) - set(cur)) if prev_rows else []}


# ---------------------------------------------------------------- status
def utc_now():
    return datetime.now(timezone.utc)


def write_status(rows, source_results, now=None, raw_dir=RAW_DIR,
                 status_path=STATUS_JSON):
    """data/status.json. `source_results` = [{'name','ok','count'}, ...]."""
    now = now or utc_now()
    prev, latest = split_last_two(rows)
    mv = compute_moves(prev, latest)
    dates = raw_dates(raw_dir)
    status = {
        "run_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "first_run_date": dates[0] if dates else None,
        "days_with_success": len(dates),
        "items": len(latest),
        "new_today": mv["appeared"],
        "gone_today": mv["gone"],
        "sources": source_results,
    }
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    with open(status_path, "w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=2)
        fh.write("\n")
    return status


def derive_source_results(date, raw_dir=RAW_DIR):
    """Source results from the raw files of `date` (used by a bare rebuild)."""
    out = []
    snap = os.path.join(raw_dir, date, CITIES_SNAPSHOT)
    cities = parse_cities(read_gz(snap).decode()) if os.path.exists(snap) else load_cities()
    for name in SOURCES:
        p = raw_path(raw_dir, date, name)
        count, ok = 0, False
        if os.path.exists(p):
            try:
                count = count_with_data(convert_source(name, json.loads(read_gz(p)), cities))
                ok = True
            except (ValueError, OSError, json.JSONDecodeError):
                pass
        out.append({"name": name, "ok": ok, "count": count})
    return out
