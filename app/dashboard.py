"""Numbers for the dashboard page (/dashboard) and its JSON twin (/api/dashboard).

A pure function over the ticket list, so it is easy to test with fixed data.
Days are counted in the display time zone (Asia/Almaty), not in UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

from app.sla import Priority, Status

OPEN = (Status.NEW, Status.IN_PROGRESS)
DONE = (Status.RESOLVED, Status.CLOSED)


def compute(tickets: list[dict], now: datetime, tz: ZoneInfo, days: int = 7) -> dict:
    """`tickets` must already carry response_breached / resolve_breached flags."""
    open_tickets = [t for t in tickets if t["status"] in OPEN]
    done = [t for t in tickets if t["status"] in DONE and t["resolved_at"]]

    # SLA compliance: resolved tickets that had a deadline and met it
    with_deadline = [t for t in done if t["resolve_due"]]
    met = [t for t in with_deadline if t["resolved_at"] <= t["resolve_due"]]
    compliance = round(100 * len(met) / len(with_deadline)) if with_deadline else None

    resolve_hours = [(t["resolved_at"] - t["created_at"]).total_seconds() / 3600 for t in done]

    # created / resolved per local day, oldest first, today last
    today = now.astimezone(tz).date()
    day_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    created = dict.fromkeys(day_list, 0)
    resolved = dict.fromkeys(day_list, 0)
    for t in tickets:
        d = t["created_at"].astimezone(tz).date()
        if d in created:
            created[d] += 1
        if t["resolved_at"]:
            d = t["resolved_at"].astimezone(tz).date()
            if d in resolved:
                resolved[d] += 1

    breached_open = [t for t in open_tickets if t["response_breached"] or t["resolve_breached"]]
    # what an operator should look at first: breached, then most urgent priority, then deadline
    far_future = now + timedelta(days=3650)
    urgent = sorted(
        open_tickets,
        key=lambda t: (
            not (t["response_breached"] or t["resolve_breached"]),
            t["priority"],
            t["resolve_due"] or far_future,
        ),
    )[:5]

    return {
        "total": len(tickets),
        "open": len(open_tickets),
        "open_p1": sum(t["priority"] == Priority.P1 for t in open_tickets),
        "breached_open": len(breached_open),
        "sla_compliance": compliance,
        "avg_resolve_hours": round(mean(resolve_hours), 1) if resolve_hours else None,
        "by_status": {s.value: sum(t["status"] == s for t in tickets) for s in Status},
        "open_by_priority": {
            p.value: sum(t["priority"] == p for t in open_tickets) for p in Priority
        },
        "days": [
            {"date": d.isoformat(), "created": created[d], "resolved": resolved[d]}
            for d in day_list
        ],
        "urgent": urgent,
        "by_assignee": by_assignee(open_tickets),
    }


def by_assignee(open_tickets: list[dict]) -> list[dict]:
    """Open tickets per person, busiest first; the unassigned bucket always goes last."""
    counts: dict[str, int] = {}
    for t in open_tickets:
        name = (t.get("assignee") or "").strip()
        counts[name] = counts.get(name, 0) + 1
    named = sorted(((n, c) for n, c in counts.items() if n), key=lambda x: (-x[1], x[0].casefold()))
    rows = [{"name": n, "count": c} for n, c in named]
    if counts.get(""):
        rows.append({"name": None, "count": counts[""]})
    return rows
