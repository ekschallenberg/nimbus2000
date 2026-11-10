import report
import tracker as t


def row(date, iid, temp):
    r = {c: "" for c in t.COLUMNS}
    r.update(date=date, item_id=iid, item=iid.title(), source="open-meteo", temperature_2m=str(temp))
    return r


def test_report_titled_with_date_even_on_first_run():
    title, body = report.build_report([row("2026-01-01", "a", 1)])
    assert title == "2026-01-01" and "First run" in body


def test_report_lists_moves_and_appearances():
    rows = [row("2026-01-01", "a", 1), row("2026-01-01", "b", 5),
            row("2026-01-02", "a", 4), row("2026-01-02", "c", 9)]
    title, body = report.build_report(rows)
    assert title == "2026-01-02"
    assert "| A | temperature_2m | 1 | 4 | +3 °C |" in body
    assert "### Appeared\n\n- c" in body and "### Disappeared\n\n- b" in body


def test_report_with_no_changes_still_produced():
    rows = [row("2026-01-01", "a", 1), row("2026-01-02", "a", 1)]
    title, body = report.build_report(rows)
    assert title == "2026-01-02" and "None." in body


class FakeGitHub:
    def __init__(self, issues):
        self.issues, self.calls = issues, []

    def __call__(self, method, url, token, data=None):
        self.calls.append((method, url.split("/repos/r/r")[-1], data))
        if method == "GET":
            return self.issues
        if method == "POST" and url.endswith("/issues"):
            return {"number": 99}
        return {}


def test_publish_opens_new_issue_and_closes_previous():
    gh = FakeGitHub([{"number": 5, "title": "2026-01-01", "state": "open"}])
    res = report.publish("r/r", "tok", "2026-01-02", "body", call=gh)
    assert res == {"action": "opened", "number": 99, "closed": [5]}
    assert ("PATCH", "/issues/5", {"state": "closed", "state_reason": "completed"}) in gh.calls


def test_publish_second_run_updates_same_days_issue():
    gh = FakeGitHub([{"number": 7, "title": "2026-01-02", "state": "open"},
                     {"number": 5, "title": "2026-01-01", "state": "closed"}])
    res = report.publish("r/r", "tok", "2026-01-02", "new body", call=gh)
    assert res == {"action": "updated", "number": 7, "closed": []}
    assert ("PATCH", "/issues/7", {"body": "new body", "state": "open"}) in gh.calls
    assert not any(m == "POST" and u == "/issues" for m, u, _ in gh.calls)
