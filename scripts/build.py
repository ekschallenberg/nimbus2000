#!/usr/bin/env python3
"""Rebuild data/history.csv and data/status.json from data/raw/ alone.

    python scripts/build.py
"""
import sys

import tracker as t


def main():
    rows = t.build_history()
    dates = t.raw_dates()
    results = t.derive_source_results(dates[-1]) if dates else []
    st = t.write_status(rows, results)
    print("built %d rows over %d days; %d items in the latest run"
          % (len(rows), len(dates), st["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
