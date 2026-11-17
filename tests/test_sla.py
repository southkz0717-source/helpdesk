from datetime import UTC, datetime, timedelta

from app.sla import Priority, Status, can_transition, due_dates, is_breached

T0 = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


def test_p1_deadlines():
    response, resolve = due_dates(Priority.P1, T0)
    assert response == T0 + timedelta(minutes=15)
    assert resolve == T0 + timedelta(hours=8)


def test_p2_deadlines():
    response, resolve = due_dates(Priority.P2, T0)
    assert response == T0 + timedelta(hours=2)
    assert resolve == T0 + timedelta(days=2)


def test_p4_has_no_commitment():
    assert due_dates(Priority.P4, T0) == (None, None)


def test_breach_when_not_done_and_deadline_passed():
    assert is_breached(T0, None, T0 + timedelta(minutes=1))


def test_no_breach_when_done_in_time():
    assert not is_breached(T0, T0 - timedelta(minutes=1), T0 + timedelta(days=1))


def test_no_breach_without_deadline():
    assert not is_breached(None, None, T0)


def test_allowed_transitions():
    assert can_transition(Status.NEW, Status.IN_PROGRESS)
    assert can_transition(Status.RESOLVED, Status.IN_PROGRESS)  # reopen
    assert not can_transition(Status.CLOSED, Status.IN_PROGRESS)
    assert not can_transition(Status.NEW, Status.CLOSED)
