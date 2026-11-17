import random
from collections import Counter
from datetime import UTC, datetime

from scripts.seed import seed

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def test_seed_fills_realistic_data(client):
    assert seed(200, random.Random(11), NOW) == 200
    tickets = client.get("/api/tickets", params={"limit": 500}).json()
    assert len(tickets) == 200
    priorities = Counter(t["priority"] for t in tickets)
    assert priorities["P3"] > priorities["P1"]  # realistic mix: few critical tickets
    assert {t["status"] for t in tickets} == {"new", "in_progress", "resolved", "closed"}
    # old open tickets breach their SLA, so UAT can check the "SLA breached" mark
    assert any(t["resolve_breached"] for t in tickets)
    # resolved tickets have consistent timestamps
    for t in tickets:
        if t["status"] in ("resolved", "closed"):
            assert t["first_response_at"] <= t["resolved_at"]


def test_seed_is_reproducible(client):
    seed(30, random.Random(5), NOW)
    first = [t["title"] for t in client.get("/api/tickets", params={"limit": 500}).json()]
    assert len(first) == 30
    # same seed -> same tickets (the order of the queue is deterministic too)
    seed(30, random.Random(5), NOW)
    second = [t["title"] for t in client.get("/api/tickets", params={"limit": 500}).json()]
    assert sorted(second) == sorted(first * 2)
