import sqlite3

from app import db
from app.sla import Priority, Status

OLD_SCHEMA = """
CREATE TABLE tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    requester TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
    response_due TEXT, resolve_due TEXT, first_response_at TEXT, resolved_at TEXT
);
INSERT INTO tickets (title, requester, priority, status, created_at)
VALUES ('Old ticket', 'Dana', 'P3', 'new', '2026-11-01T09:00:00+00:00');
"""


def test_migration_from_v040_keeps_data(tmp_path, monkeypatch):
    """A v0.4.0 database gains the new column and table; old rows stay intact."""
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
    monkeypatch.setenv("HELPDESK_DB", str(path))

    db.init_db()
    db.init_db()  # idempotent: running twice must not fail

    t = db.get_ticket(1)
    assert t["title"] == "Old ticket" and t["assignee"] is None
    assert db.list_events(1) == []
    # v0.4.0 only reads the columns it knows, so rolling back stays possible
    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tickets)")]
    assert cols[:11] == ["id", "title", "description", "requester", "priority", "status",
                         "created_at", "response_due", "resolve_due", "first_response_at",
                         "resolved_at"]  # fmt: skip


def test_history_records_status_assign_and_comment(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_DB", str(tmp_path / "h.db"))
    db.init_db()
    tid = db.create_ticket("VPN", "", "Dana", Priority.P2)["id"]

    db.assign(tid, "Ерлан", author="Айгерім")
    db.assign(tid, "Ерлан")  # same assignee again: no new event
    db.set_status(tid, Status.IN_PROGRESS, author="Ерлан")
    db.add_comment(tid, "Ерлан", "Қайта қосылдым, тексеріп жатырмын")

    kinds = [(e["kind"], e["from_value"], e["to_value"]) for e in db.list_events(tid)]
    assert kinds == [
        ("assigned", None, "Ерлан"),
        ("status", "new", "in_progress"),
        ("comment", None, None),
    ]
    assert db.list_events(tid)[-1]["body"] == "Қайта қосылдым, тексеріп жатырмын"
    assert db.get_ticket(tid)["assignee"] == "Ерлан"

    db.assign(tid, "  ")  # blank = unassign
    assert db.get_ticket(tid)["assignee"] is None
    assert db.list_events(tid)[-1]["to_value"] is None


def test_filters_sort_and_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_DB", str(tmp_path / "f.db"))
    db.init_db()
    ids = [db.create_ticket(f"T{i}", "", "Dana", Priority.P3)["id"] for i in range(5)]
    p1 = db.create_ticket("Urgent", "", "Dana", Priority.P1)["id"]
    db.assign(ids[0], "Ерлан")
    db.assign(p1, "Ерлан")

    assert [t["id"] for t in db.list_tickets(limit=2)] == [p1, ids[0]]  # queue: P1 first
    assert [t["id"] for t in db.list_tickets(limit=2, offset=2)] == ids[1:3]
    assert db.list_tickets(sort="newest", limit=1)[0]["id"] == p1
    assert db.list_tickets(sort="oldest", limit=1)[0]["id"] == ids[0]
    assert db.list_tickets(sort="due", limit=1)[0]["id"] == p1  # 8 h deadline is the nearest
    assert db.count_tickets(assignee="Ерлан") == 2
    assert db.count_tickets(assignee=db.UNASSIGNED) == 4
    assert db.list_assignees() == ["Ерлан"]
    assert db.list_tickets(sort="'; DROP TABLE tickets; --")  # unknown sort -> default, no SQL
