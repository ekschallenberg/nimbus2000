# Nimbus 2000: daily weather and air quality tracker

[![tests](https://github.com/ekschallenberg/nimbus2000/actions/workflows/tests.yml/badge.svg)](https://github.com/ekschallenberg/nimbus2000/actions/workflows/tests.yml)
[![daily](https://github.com/ekschallenberg/nimbus2000/actions/workflows/daily.yml/badge.svg)](https://github.com/ekschallenberg/nimbus2000/actions/workflows/daily.yml)

**Weather data by Open-Meteo.com** (licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).

## What this is

Every day GitHub Actions downloads the current weather and air quality for 12 cities from
[Open-Meteo](https://open-meteo.com/) (free, no API key, no login), saves the raw responses,
rebuilds a history with one row per city per UTC date, opens a GitHub Issue with the biggest
moves, and commits the results. A static site (GitHub Pages) shows the data.

Site: https://ekschallenberg.github.io/nimbus2000/ (Today, Browse, Trends; installable as an app,
works offline with the last data it loaded).

## The key

Each city has a stable lowercase slug in the `key` column of `cities.csv` (for example
`fayetteville-ar`, `sao-paulo`). It becomes `item_id` in the history and lines the same city up
from day to day. Adding a city is a one-line edit to `cities.csv`; no code changes.
Because results are matched to cities **by position in the request order**, each day's raw data is
stored with a snapshot of the city list used (`cities.csv.gz`), so later edits to `cities.csv`
never misalign old days.

## Sources

| Name (status/raw file) | URL | Format | Fields requested |
|---|---|---|---|
| `weather` | `https://api.open-meteo.com/v1/forecast` (`timezone=UTC`) | JSON | temperature_2m, relative_humidity_2m, wind_speed_10m, precipitation, pressure_msl |
| `air_quality` | `https://air-quality-api.open-meteo.com/v1/air-quality` | JSON | us_aqi, pm2_5, pm10, ozone |

All cities go in one request per source (comma-separated lat/lon). Several locations return a JSON
array in request order; a single location returns a plain object (handled). The result count must
equal the city count or the source counts as failed.

**What is kept:** the requests ask only for the `current` fields above, so the API returns just
those values plus small metadata (units, grid coordinates, timestamp). The raw response is saved
gzip-compressed as received (`data/raw/<date>/<source>.json.gz`); `data/history.csv` keeps only
the fields listed below.

## Files

| Path | What it does |
|---|---|
| `cities.csv` | The 12 tracked cities: `key,name,lat,lon`. |
| `scripts/fetch.py` | Daily entry point (stdlib only): fetch each source (User-Agent, 30 s timeout, 3 retries with backoff), save raw files, rebuild history, write status. Exits non-zero if a request failed or fewer than 10 cities have data, after writing everything. |
| `scripts/tracker.py` | Shared logic: converting raw responses to rows, building history, the move rule, status. |
| `scripts/build.py` | Rebuilds `data/history.csv` and `data/status.json` from `data/raw/` alone. |
| `scripts/report.py` | Builds the daily Issue text; `--publish` opens/updates today's Issue and closes older ones. |
| `scripts/make_icons.py` | Generates the app icons. |
| `data/raw/<date>/` | `weather.json.gz`, `air_quality.json.gz`, `cities.csv.gz` (city list snapshot). |
| `data/history.csv` | One row per city per UTC date (see columns below). |
| `data/status.json` | Latest run: `run_time`, `first_run_date`, `days_with_success`, `items`, `new_today`, `gone_today`, `sources` (`name`, `ok`, `count`). |
| `index.html` | Today: last run, source status, counts, latest values with change, biggest moves. |
| `browse.html` | Browse: filters, search, sort, starred shortlist (saved in the browser). |
| `trends.html` | Trends: charts of every value and five findings, all computed in the browser from the history file. |
| `app.js`, `style.css` | Shared navigation, data loading, charts and styles. |
| `manifest.webmanifest`, `sw.js`, `icon-*.png` | Installable app: manifest, service worker (network first, cached fallback), icons. |
| `tests/` | pytest suite. |
| `.github/workflows/daily.yml` | Daily pipeline. |
| `.github/workflows/tests.yml` | Runs pytest on every push. |

## `data/history.csv` columns

Rows are sorted by `date`, then `item_id`. A value the source did not report is left empty.
There is one row per city per date; the two sources are merged into that row.

| Column | Meaning | Unit |
|---|---|---|
| `date` | UTC date of the run | YYYY-MM-DD |
| `item_id` | City key from `cities.csv` | slug |
| `item` | City name | text |
| `source` | Data provider | `open-meteo` |
| `observed_at_utc` | Observation time (weather's if present, else air quality's) | UTC, `YYYY-MM-DDTHH:MM` |
| `temperature_2m` | Air temperature at 2 m | °C |
| `relative_humidity_2m` | Relative humidity at 2 m | % |
| `wind_speed_10m` | Wind speed at 10 m | km/h |
| `precipitation` | Precipitation in the current interval | mm |
| `pressure_msl` | Mean sea-level pressure | hPa |
| `us_aqi` | US Air Quality Index | index (0-500) |
| `pm2_5` | Fine particulate matter | µg/m³ |
| `pm10` | Coarse particulate matter | µg/m³ |
| `ozone` | Ozone | µg/m³ |

Only these fields are kept from each response.

## Rebuild the history from the raw files

```bash
python scripts/build.py
```

The history depends on the raw files alone, so this reproduces `data/history.csv` exactly, and a
change to a rule applies to every day. A second run on the same day replaces that day's raw files
and rows; it never duplicates them.

## The move rule

Between the latest run and the previous run, for every city present in both and every numeric
column with a value in both: `score = |new - old| / sd`, where `sd` is the population standard
deviation of that column across all cities in the latest run (1 if it is 0 or there are fewer than
2 values). This makes degrees, hPa and AQI comparable. The 10 highest scores are the biggest moves.
Cities only in the latest run appeared; cities only in the previous run disappeared. The Issue and
the Today page use the same rule.

## Schedule and manual runs

`daily.yml` runs at **06:15 UTC every day** and on demand. To run it manually: GitHub → Actions →
*daily* → *Run workflow*. Each run: fetch → raw files → history → status → commit (only if
something changed, as `github-actions[bot]`) → open/update the Issue titled with the date and close
the previous day's Issue. If a source fails, the other still runs and the data is committed, then
the run is marked red. No secrets are needed. If a keyed source is ever added, pass it to the step
as `env: KEY: ${{ secrets.KEY }}` and never write it to a file.

Run locally:

```bash
python scripts/fetch.py
python -m pip install pytest && python -m pytest
```

## Replacing the source

If Open-Meteo stops working, swap in another source behind the same CSV columns: change
`SOURCES` and `convert_source` in `scripts/tracker.py` (and the request in `scripts/fetch.py`),
keep `COLUMNS` unchanged, and note the change here.

Source change log: none yet.
