#!/usr/bin/env python3
"""Daily pipeline step: fetch -> raw files -> history.csv -> status.json.

Standard library only. Exit code is non-zero when a request failed or fewer
than 10 cities have data, but only AFTER the raw files, history and status
have been written, so the workflow can still commit what it got.
"""
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import tracker as t

USER_AGENT = "nimbus2000-data-tracker/1.0 (+https://github.com/ekschallenberg/nimbus2000)"
TIMEOUT = 30
RETRIES = 3
BACKOFF = 2  # seconds, doubled each retry


def build_url(source, cities):
    s = t.SOURCES[source]
    q = {"latitude": ",".join(c["lat"] for c in cities),
         "longitude": ",".join(c["lon"] for c in cities),
         "current": ",".join(s["fields"])}
    q.update(s["extra"])
    return s["url"] + "?" + urllib.parse.urlencode(q, safe=",")


def http_get(url, sleep=time.sleep, opener=urllib.request.urlopen):
    """GET with User-Agent, timeout and 3 retries (backoff 2s, 4s, 8s)."""
    last = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "application/json"})
            with opener(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            if attempt < RETRIES:
                wait = BACKOFF * (2 ** attempt)
                print("  attempt %d failed (%s); retrying in %ds" % (attempt + 1, exc, wait))
                sleep(wait)
    raise RuntimeError("request failed after %d retries: %s" % (RETRIES, last))


def fetch_source(source, cities, getter=http_get):
    """-> (raw_bytes, converted). Raises if the request or the shape is bad."""
    body = getter(build_url(source, cities))
    payload = json.loads(body)
    converted = t.convert_source(source, payload, cities)  # asserts count == cities
    return body, converted


def run(date, cities, raw_dir=t.RAW_DIR, history_path=t.HISTORY_CSV,
        status_path=t.STATUS_JSON, getter=http_get, now=None):
    """Fetch every source, write raw files, rebuild history, write status.

    Returns (ok, status). One failing source never stops the others.
    """
    results, any_failed = [], False
    for name in t.SOURCES:
        print("fetching %s ..." % name)
        try:
            body, converted = fetch_source(name, cities, getter)
            n = t.count_with_data(converted)
            t.write_gz(t.raw_path(raw_dir, date, name), body)
            results.append({"name": name, "ok": True, "count": n})
            print("  ok: %d/%d cities have data" % (n, len(cities)))
            if n < t.MIN_CITIES:
                any_failed = True
                print("  ERROR: fewer than %d cities have data" % t.MIN_CITIES)
        except Exception as exc:  # noqa: BLE001 - record any failure, keep going
            any_failed = True
            results.append({"name": name, "ok": False, "count": 0})
            print("  FAILED: %s" % exc)
    # snapshot of the city list the requests were built from, so the build
    # never depends on a cities.csv that may have changed since
    if any(r["ok"] for r in results):
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["key", "name", "lat", "lon"])
        for c in cities:
            w.writerow([c["key"], c["name"], c["lat"], c["lon"]])
        t.write_gz(os.path.join(raw_dir, date, t.CITIES_SNAPSHOT), buf.getvalue().encode("utf-8"))
    rows = t.build_history(raw_dir, history_path, fallback_cities=cities)
    status = t.write_status(rows, results, now=now, raw_dir=raw_dir, status_path=status_path)
    return (not any_failed), status


def main():
    now = t.utc_now()
    date = now.strftime("%Y-%m-%d")
    cities = t.load_cities()
    ok, status = run(date, cities, now=now)
    print("date=%s items=%d days_with_success=%d" %
          (date, status["items"], status["days_with_success"]))
    if not ok:
        print("pipeline finished with errors", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
