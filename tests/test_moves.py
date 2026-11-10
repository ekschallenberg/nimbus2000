import math

import tracker as t


def row(iid, **vals):
    r = {"date": "d", "item_id": iid, "item": iid.upper()}
    r.update({c: "" for c in t.NUMERIC})
    r.update({k: str(v) for k, v in vals.items()})
    return r


def test_score_is_change_over_latest_day_sd():
    prev = [row("a", temperature_2m=10), row("b", temperature_2m=20)]
    cur = [row("a", temperature_2m=14), row("b", temperature_2m=20)]
    sd = math.sqrt(((14 - 17) ** 2 + (20 - 17) ** 2) / 2)  # population sd = 3
    mv = t.compute_moves(prev, cur)["moves"]
    assert len(mv) == 2
    top = mv[0]
    assert (top["item_id"], top["column"], top["old"], top["new"]) == ("a", "temperature_2m", 10, 14)
    assert top["change"] == 4 and abs(top["score"] - 4 / sd) < 1e-9
    assert mv[1]["score"] == 0


def test_ranking_across_columns_uses_normalised_scores():
    prev = [row("a", temperature_2m=10, pressure_msl=1000), row("b", temperature_2m=10, pressure_msl=1000)]
    cur = [row("a", temperature_2m=11, pressure_msl=1010), row("b", temperature_2m=9, pressure_msl=1000)]
    mv = t.compute_moves(prev, cur)["moves"]
    # pressure +10 on sd 5 (score 2) beats temperature +1 on sd 1 (score 1)
    assert (mv[0]["item_id"], mv[0]["column"]) == ("a", "pressure_msl")


def test_limit_and_zero_sd_fallback():
    prev = [row("a", ozone=5)]
    cur = [row("a", ozone=8)]
    mv = t.compute_moves(prev, cur, limit=1)["moves"]
    assert len(mv) == 1 and mv[0]["score"] == 3  # one value -> sd treated as 1


def test_empty_values_are_skipped():
    prev = [row("a", temperature_2m=10)]
    cur = [row("a", temperature_2m="")]
    assert t.compute_moves(prev, cur)["moves"] == []


def test_appeared_and_gone():
    prev = [row("a", temperature_2m=1), row("b", temperature_2m=1)]
    cur = [row("b", temperature_2m=2), row("c", temperature_2m=3)]
    r = t.compute_moves(prev, cur)
    assert r["appeared"] == ["c"] and r["gone"] == ["a"]
    assert {m["item_id"] for m in r["moves"]} == {"b"}


def test_first_run_has_no_comparison():
    r = t.compute_moves([], [row("a", temperature_2m=1)])
    assert r == {"moves": [], "appeared": [], "gone": []}


def test_split_last_two():
    rows = [dict(row("a"), date="2026-01-02"), dict(row("a"), date="2026-01-01"),
            dict(row("b"), date="2026-01-03")]
    prev, latest = t.split_last_two(rows)
    assert [r["date"] for r in prev] == ["2026-01-02"]
    assert [r["item_id"] for r in latest] == ["b"]
