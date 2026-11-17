from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def make_ticket(client, priority="P2", title="Принтер не печатает"):
    resp = client.post(
        "/api/tickets",
        json={"title": title, "requester": "Айгерим", "priority": priority},
    )
    assert resp.status_code == 201
    return resp.json()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_ticket_sets_sla(client):
    ticket = make_ticket(client, priority="P1")
    assert ticket["status"] == "new"
    assert ticket["response_due"] is not None
    assert ticket["resolve_breached"] is False


def test_create_ticket_validation(client):
    resp = client.post("/api/tickets", json={"title": "x", "requester": "A", "priority": "P9"})
    assert resp.status_code == 422


def test_get_missing_ticket(client):
    assert client.get("/api/tickets/999").status_code == 404


def test_full_lifecycle(client):
    ticket = make_ticket(client)
    tid = ticket["id"]
    for status in ("in_progress", "resolved", "closed"):
        resp = client.post(f"/api/tickets/{tid}/status", json={"status": status})
        assert resp.status_code == 200
        assert resp.json()["status"] == status
    final = client.get(f"/api/tickets/{tid}").json()
    assert final["first_response_at"] is not None
    assert final["resolved_at"] is not None


def test_forbidden_transition(client):
    tid = make_ticket(client)["id"]
    resp = client.post(f"/api/tickets/{tid}/status", json={"status": "closed"})
    assert resp.status_code == 409


def test_filter_by_priority(client):
    make_ticket(client, priority="P1")
    make_ticket(client, priority="P3")
    resp = client.get("/api/tickets", params={"priority": "P1"})
    assert [t["priority"] for t in resp.json()] == ["P1"]


def test_stats(client):
    make_ticket(client, priority="P1")
    make_ticket(client, priority="P1")
    stats = client.get("/api/stats").json()
    assert stats["total"] == 2
    assert stats["open_by_priority"]["P1"] == 2


@pytest.mark.parametrize(
    "lang,text", [("kk", "Қолдау қызметі"), ("ru", "Служба поддержки"), ("en", "Helpdesk")]
)
def test_ui_languages(client, lang, text):
    resp = client.get("/", params={"lang": lang})
    assert resp.status_code == 200
    assert text in resp.text


def test_ui_create_ticket_form(client):
    resp = client.post(
        "/tickets",
        data={"title": "Нет доступа к почте", "requester": "Ерлан", "priority": "P2", "lang": "ru"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Нет доступа к почте" in resp.text


def test_ui_form_validation(client):
    resp = client.post("/tickets", data={"title": "x", "requester": "Ерлан", "priority": "P2"})
    assert resp.status_code == 422


def test_ticket_page_shows_local_time(client, monkeypatch):
    monkeypatch.delenv("HELPDESK_TZ", raising=False)
    tid = make_ticket(client)["id"]
    ticket = client.get(f"/api/tickets/{tid}").json()
    created_utc = datetime.fromisoformat(ticket["created_at"])
    page = client.get(f"/tickets/{tid}").text
    assert (created_utc + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M") in page
    assert "UTC+5" in page


def test_health_reports_version(client):
    assert client.get("/health").json()["version"] == "0.2.0"
