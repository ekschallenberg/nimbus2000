#!/usr/bin/env python3
"""Daily GitHub Issue: biggest moves since the previous run (stdlib only).

    python scripts/report.py            # print title and body
    python scripts/report.py --publish  # open/update today's issue, close old ones

--publish reads GITHUB_TOKEN and GITHUB_REPOSITORY from the environment; the
token is never written to a file.
"""
import json
import os
import sys
import urllib.error
import urllib.request

import tracker as t

LABEL = "daily-report"
UNITS = {"temperature_2m": "°C", "relative_humidity_2m": "%", "wind_speed_10m": "km/h",
         "precipitation": "mm", "pressure_msl": "hPa", "us_aqi": "AQI",
         "pm2_5": "µg/m³", "pm10": "µg/m³", "ozone": "µg/m³"}


def fmt(v):
    return ("%.2f" % v).rstrip("0").rstrip(".")


def build_report(rows):
    """-> (title, markdown body). Always produces an issue, even with no moves."""
    dates = sorted({r["date"] for r in rows})
    if not dates:
        return t.utc_now().strftime("%Y-%m-%d"), "No data has been collected yet.\n"
    title = dates[-1]
    prev, latest = t.split_last_two(rows)
    lines = ["## Daily report for %s" % title, ""]
    if not prev:
        lines += ["First run: there is no previous run to compare with.", ""]
    mv = t.compute_moves(prev, latest)
    if prev:
        lines += ["Compared with %s. %d items in this run." % (dates[-2], len(latest)), ""]
        if mv["moves"]:
            lines += ["### Biggest moves", "",
                      "| # | Item | Value | Old | New | Change | Score |",
                      "|--:|---|---|--:|--:|--:|--:|"]
            for i, m in enumerate(mv["moves"], 1):
                u = UNITS.get(m["column"], "")
                lines.append("| %d | %s | %s | %s | %s | %s%s | %.2f |" % (
                    i, m["item"], m["column"], fmt(m["old"]), fmt(m["new"]),
                    "+" if m["change"] > 0 else "", fmt(m["change"]) + (" " + u if u else ""),
                    m["score"]))
            lines.append("")
        else:
            lines += ["No comparable values moved.", ""]
        lines += ["### Appeared", ""] + (["- " + k for k in mv["appeared"]] or ["None."]) + [""]
        lines += ["### Disappeared", ""] + (["- " + k for k in mv["gone"]] or ["None."]) + [""]
    lines += ["---",
              "Move rule: score = |new - old| / sd, sd being the standard deviation of that "
              "column across all items in the latest run. The %d largest scores are listed. "
              "Weather data by [Open-Meteo.com](https://open-meteo.com/)." % t.MOVE_LIMIT]
    return title, "\n".join(lines) + "\n"


# --------------------------------------------------------------- GitHub API
def api(method, url, token, data=None, opener=urllib.request.urlopen):
    req = urllib.request.Request(
        url, method=method, data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "User-Agent": "nimbus2000-data-tracker", "Content-Type": "application/json"})
    with opener(req, timeout=30) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def publish(repo, token, title, body, call=api):
    """Create or update the issue titled `title`; close every other open one."""
    base = "https://api.github.com/repos/%s" % repo
    try:
        call("POST", base + "/labels", token, {"name": LABEL, "color": "0e8a16"})
    except urllib.error.HTTPError:
        pass  # label already exists
    issues = call("GET", base + "/issues?state=all&labels=%s&per_page=100" % LABEL, token)
    same = [i for i in issues if i["title"] == title and "pull_request" not in i]
    if same:
        num = same[0]["number"]
        call("PATCH", "%s/issues/%d" % (base, num), token,
             {"body": body, "state": "open"})
        action = "updated"
    else:
        num = call("POST", base + "/issues", token,
                   {"title": title, "body": body, "labels": [LABEL]})["number"]
        action = "opened"
    closed = []
    for i in issues:
        if i["number"] != num and i["state"] == "open" and "pull_request" not in i:
            call("PATCH", "%s/issues/%d" % (base, i["number"]), token,
                 {"state": "closed", "state_reason": "completed"})
            closed.append(i["number"])
    return {"action": action, "number": num, "closed": closed}


def main(argv):
    title, body = build_report(t.read_history())
    if "--publish" in argv:
        res = publish(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"], title, body)
        print("issue #%d %s; closed %s" % (res["number"], res["action"], res["closed"] or "none"))
    else:
        print("TITLE:", title)
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
