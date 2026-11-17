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
"""


def db_path() -> str:
    return os.environ.get("HELPDESK_DB", "helpdesk.db")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    # SQLite's LOWER() and LIKE ignore case only for ASCII; this handles Cyrillic and Kazakh
    conn.create_function("casefold", 1, lambda s: s.casefold() if s else "", deterministic=True)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    for key in ("created_at", "response_due", "resolve_due", "first_response_at", "resolved_at"):
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


def list_tickets(
    status: Status | None = None, priority: Priority | None = None, q: str | None = None
) -> list[dict]:
    query = "SELECT * FROM tickets WHERE 1=1"
    params: list[str] = []
    if q and q.strip():
        needle = q.strip().casefold()
        query += (
            " AND (instr(casefold(title), ?) > 0 OR instr(casefold(requester), ?) > 0"
            " OR instr(casefold(description), ?) > 0)"
        )
        params += [needle, needle, needle]
    if status:
        query += " AND status = ?"
        params.append(status.value)
    if priority:
        query += " AND priority = ?"
        params.append(priority.value)
    query += " ORDER BY priority, created_at"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def set_status(ticket_id: int, new_status: Status) -> dict:
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
    return get_ticket(ticket_id)
