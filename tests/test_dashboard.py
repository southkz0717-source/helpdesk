from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.dashboard import compute

TZ = ZoneInfo("Asia/Almaty")
NOW = datetime(2026, 11, 19, 6, 0, tzinfo=UTC)  # 11:00 in Almaty
H = timedelta(hours=1)


def ticket(tid, priority="P3", status="new", created=NOW - H, resolved=None, due=NOW + 24 * H,
           breached=False):  # fmt: skip
    return {
        "id": tid, "title": f"t{tid}", "priority": priority, "status": status,
        "created_at": created, "resolved_at": resolved, "resolve_due": due,
        "response_breached": breached, "resolve_breached": False,
    }  # fmt: skip


def test_kpis():
    tickets = [
        ticket(1, "P1", "new", breached=True),
        ticket(2, "P1", "in_progress"),
        ticket(3, "P2", "resolved", created=NOW - 10 * H, resolved=NOW - 6 * H, due=NOW),  # met
        ticket(
            4, "P3", "closed", created=NOW - 50 * H, resolved=NOW - 2 * H, due=NOW - 3 * H
        ),  # late
        ticket(5, "P4", "closed", created=NOW - 5 * H, resolved=NOW - 4 * H, due=None),
    ]
    d = compute(tickets, NOW, TZ)
    assert d["total"] == 5
    assert d["open"] == 2
    assert d["open_p1"] == 2
    assert d["breached_open"] == 1
    assert d["sla_compliance"] == 50  # 1 of 2 tickets with a deadline met it
    assert d["avg_resolve_hours"] == round((4 + 48 + 1) / 3, 1)
    assert d["by_status"] == {"new": 1, "in_progress": 1, "resolved": 1, "closed": 2}
    assert d["open_by_priority"] == {"P1": 2, "P2": 0, "P3": 0, "P4": 0}


def test_days_use_local_time_and_cover_a_week():
    tickets = [
        # 2026-11-18 20:00 UTC = 2026-11-19 01:00 in Almaty -> counts as "today"
        ticket(1, created=datetime(2026, 11, 18, 20, 0, tzinfo=UTC)),
        # 2026-11-18 18:00 UTC = 23:00 in Almaty -> yesterday
        ticket(2, created=datetime(2026, 11, 18, 18, 0, tzinfo=UTC)),
        # 8 days ago: outside the window
        ticket(3, created=NOW - timedelta(days=8)),
    ]
    days = compute(tickets, NOW, TZ)["days"]
    assert [x["date"] for x in days][0] == "2026-11-13"
    assert days[-1] == {"date": "2026-11-19", "created": 1, "resolved": 0}
    assert days[-2]["created"] == 1
    assert sum(x["created"] for x in days) == 2


def test_urgent_puts_breached_first_then_priority():
    tickets = [
        ticket(1, "P1", "new"),
        ticket(2, "P3", "new", breached=True),
        ticket(3, "P2", "in_progress"),
        ticket(4, "P1", "closed", resolved=NOW),
    ]
    assert [t["id"] for t in compute(tickets, NOW, TZ)["urgent"]] == [2, 1, 3]


def test_empty_database():
    d = compute([], NOW, TZ)
    assert d["open"] == 0 and d["sla_compliance"] is None and d["avg_resolve_hours"] is None
    assert len(d["days"]) == 7 and d["urgent"] == []


def test_load_by_assignee():
    tickets = [
        ticket(1, "P1", "new") | {"assignee": "Ерлан"},
        ticket(2, "P2", "in_progress") | {"assignee": "Ерлан"},
        ticket(3, "P3", "new") | {"assignee": "Айгерім"},
        ticket(4, "P3", "new"),
        ticket(5, "P3", "closed", resolved=NOW) | {"assignee": "Айгерім"},  # closed: not load
    ]
    assert compute(tickets, NOW, TZ)["by_assignee"] == [
        {"name": "Ерлан", "count": 2},
        {"name": "Айгерім", "count": 1},
        {"name": None, "count": 1},
    ]
