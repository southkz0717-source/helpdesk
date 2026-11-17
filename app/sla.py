"""SLA rules for ticket priorities (lecture 11, slide 22)."""

from datetime import datetime, timedelta
from enum import StrEnum


class Priority(StrEnum):
    P1 = "P1"  # critical: system unavailable, data lost or corrupted
    P2 = "P2"  # high: key scenario broken, workaround exists
    P3 = "P3"  # medium: inconvenience, workaround exists
    P4 = "P4"  # low: cosmetic, rare scenario


class Status(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


# (response time, resolution time); None means "no commitment"
SLA: dict[Priority, tuple[timedelta | None, timedelta | None]] = {
    Priority.P1: (timedelta(minutes=15), timedelta(hours=8)),
    Priority.P2: (timedelta(hours=2), timedelta(days=2)),
    Priority.P3: (timedelta(days=1), timedelta(days=14)),
    Priority.P4: (None, None),
}

# Allowed status transitions
TRANSITIONS: dict[Status, set[Status]] = {
    Status.NEW: {Status.IN_PROGRESS, Status.RESOLVED},
    Status.IN_PROGRESS: {Status.RESOLVED},
    Status.RESOLVED: {Status.CLOSED, Status.IN_PROGRESS},
    Status.CLOSED: set(),
}


def due_dates(priority: Priority, created_at: datetime) -> tuple[datetime | None, datetime | None]:
    """Return (response_due, resolve_due) for a ticket created at `created_at`."""
    response, resolve = SLA[priority]
    return (
        created_at + response if response else None,
        created_at + resolve if resolve else None,
    )


def can_transition(current: Status, new: Status) -> bool:
    return new in TRANSITIONS[current]


def is_breached(due: datetime | None, done_at: datetime | None, now: datetime) -> bool:
    """A deadline is breached if it passed before the work was done (or still not done)."""
    if due is None:
        return False
    return (done_at or now) > due
