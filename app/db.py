"""SQLite storage for tickets (standard library only)."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.sla import Priority, Status, due_dates

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    requester         TEXT NOT NULL,
    priority          TEXT NOT NULL,
    status            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    response_due      TEXT,
    resolve_due       TEXT,
    first_response_at TEXT,
    resolved_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_priority_created ON tickets (priority, created_at);

-- history of a ticket: status changes, assignments and comments (v0.5.0)
CREATE TABLE IF NOT EXISTS ticket_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id),
    kind       TEXT NOT NULL,          -- status | assigned | comment
    author     TEXT,
    body       TEXT,
    from_value TEXT,
    to_value   TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ticket ON ticket_events (ticket_id, created_at);
"""

UNASSIGNED = "__none__"  # filter value for tickets without an assignee

SORTS = {
    "queue": "priority, created_at",  # most urgent first, oldest first within a priority
    "newest": "created_at DESC",
    "oldest": "created_at",
    "due": "resolve_due IS NULL, resolve_due, priority",  # nearest deadline first
}


def db_path() -> str:
    return os.environ.get("HELPDESK_DB", "helpdesk.db")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    # timeout: wait up to 10 s for a lock instead of failing at once (load test, v0.3.1)
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA synchronous = NORMAL")  # safe with WAL, much faster commits
    # SQLite's LOWER() and LIKE ignore case only for ASCII; this handles Cyrillic and Kazakh
    conn.create_function("casefold", 1, lambda s: s.casefold() if s else "", deterministic=True)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        # WAL: readers do not block the writer and vice versa. Without it 200 concurrent
        # users got "database is locked" (HTTP 500) in the load test on v0.3.1.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        migrate(conn)


def migrate(conn: sqlite3.Connection) -> None:
    """Expand-only schema changes (release plan 6.4): add, never drop or rename.

    An older release (v0.4.0) keeps working on a database migrated by this one,
    so rolling back stays safe.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "assignee" not in columns:
        conn.execute("ALTER TABLE tickets ADD COLUMN assignee TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets (assignee)")


def now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    for key in ("created_at", "response_due", "resolve_due", "first_response_at", "resolved_at"):
        if key in data:
            data[key] = _parse(data[key])
    return data


def create_ticket(title: str, description: str, requester: str, priority: Priority) -> dict:
    created = now()
    response_due, resolve_due = due_dates(priority, created)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (title, description, requester, priority, status,"
            " created_at, response_due, resolve_due) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                description,
                requester,
                priority.value,
                Status.NEW.value,
                _iso(created),
                _iso(response_due),
                _iso(resolve_due),
            ),
        )
        ticket_id = cur.lastrowid
    return get_ticket(ticket_id)


def get_ticket(ticket_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return row_to_dict(row) if row else None


def _filters(
    status: Status | None,
    priority: Priority | None,
    q: str | None,
    assignee: str | None = None,
) -> tuple[str, list[str]]:
    where = " WHERE 1=1"
    params: list[str] = []
    if q and q.strip():
        needle = q.strip().casefold()
        where += (
            " AND (instr(casefold(title), ?) > 0 OR instr(casefold(requester), ?) > 0"
            " OR instr(casefold(description), ?) > 0)"
        )
        params += [needle, needle, needle]
    if status:
        where += " AND status = ?"
        params.append(status.value)
    if priority:
        where += " AND priority = ?"
        params.append(priority.value)
    if assignee == UNASSIGNED:
        where += " AND (assignee IS NULL OR assignee = '')"
    elif assignee:
        where += " AND assignee = ?"
        params.append(assignee)
    return where, params


def list_tickets(
    status: Status | None = None,
    priority: Priority | None = None,
    q: str | None = None,
    limit: int | None = None,
    *,
    assignee: str | None = None,
    sort: str = "queue",
    offset: int = 0,
) -> list[dict]:
    """Tickets matching the filters, in the chosen order (default: the work queue).

    `limit` keeps pages fast as the table grows: rendering every ticket made
    GET / take seconds after ~1300 tickets in the load test on v0.3.1.
    """
    where, params = _filters(status, priority, q, assignee)
    order = SORTS.get(sort, SORTS["queue"])
    query = f"SELECT * FROM tickets{where} ORDER BY {order}, id"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params += [str(limit), str(max(offset, 0))]
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def count_tickets(
    status: Status | None = None,
    priority: Priority | None = None,
    q: str | None = None,
    *,
    assignee: str | None = None,
) -> int:
    where, params = _filters(status, priority, q, assignee)
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM tickets" + where, params).fetchone()[0]


def list_assignees() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT assignee FROM tickets WHERE assignee IS NOT NULL AND assignee != ''"
            " ORDER BY casefold(assignee)"
        ).fetchall()
    return [r[0] for r in rows]


# ---------- history ----------


def _add_event(
    conn: sqlite3.Connection,
    ticket_id: int,
    kind: str,
    author: str | None = None,
    body: str | None = None,
    from_value: str | None = None,
    to_value: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO ticket_events"
        " (ticket_id, kind, author, body, from_value, to_value, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, kind, author or None, body, from_value, to_value, _iso(now())),
    )


def list_events(ticket_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY created_at, id", (ticket_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def add_comment(ticket_id: int, author: str, body: str) -> dict:
    with connect() as conn:
        _add_event(conn, ticket_id, "comment", author=author, body=body)
    return list_events(ticket_id)[-1]


def assign(ticket_id: int, assignee: str | None, author: str | None = None) -> dict:
    ticket = get_ticket(ticket_id)
    assignee = (assignee or "").strip() or None
    if assignee == ticket.get("assignee"):
        return ticket
    with connect() as conn:
        conn.execute("UPDATE tickets SET assignee = ? WHERE id = ?", (assignee, ticket_id))
        _add_event(
            conn, ticket_id, "assigned", author=author,
            from_value=ticket.get("assignee"), to_value=assignee,
        )  # fmt: skip
    return get_ticket(ticket_id)


def set_status(ticket_id: int, new_status: Status, author: str | None = None) -> dict:
    ticket = get_ticket(ticket_id)
    ts = _iso(now())
    first_response = ticket["first_response_at"]
    resolved_at = ticket["resolved_at"]
    with connect() as conn:
        if first_response is None:
            conn.execute("UPDATE tickets SET first_response_at = ? WHERE id = ?", (ts, ticket_id))
        if new_status == Status.RESOLVED:
            conn.execute("UPDATE tickets SET resolved_at = ? WHERE id = ?", (ts, ticket_id))
        elif new_status == Status.IN_PROGRESS and resolved_at is not None:
            # reopened: the ticket is no longer resolved
            conn.execute("UPDATE tickets SET resolved_at = NULL WHERE id = ?", (ticket_id,))
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (new_status.value, ticket_id))
        _add_event(
            conn, ticket_id, "status", author=author,
            from_value=ticket["status"], to_value=new_status.value,
        )  # fmt: skip
    return get_ticket(ticket_id)
