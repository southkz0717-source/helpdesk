from datetime import datetime, timedelta

import pytest


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
    assert client.get("/health").json()["version"] == "0.5.0"


def test_search_is_case_insensitive_for_cyrillic_and_kazakh(client):
    make_ticket(client, title="Принтер не печатает")
    make_ticket(client, title="Қолдау қызметіне кіру мүмкін емес")
    make_ticket(client, title="VPN disconnects")

    def titles(q):
        return [t["title"] for t in client.get("/api/tickets", params={"q": q}).json()]

    assert titles("ПРИНТЕР") == ["Принтер не печатает"]
    assert titles("қызмет") == ["Қолдау қызметіне кіру мүмкін емес"]
    assert titles("ҚОЛДАУ") == ["Қолдау қызметіне кіру мүмкін емес"]
    assert titles("vpn") == ["VPN disconnects"]
    assert titles("  ") == [t["title"] for t in client.get("/api/tickets").json()]


def test_search_by_requester_and_description(client):
    client.post(
        "/api/tickets",
        json={"title": "Нет доступа", "requester": "Ерлан", "priority": "P3",
              "description": "Не открывается корпоративная почта"},
    )  # fmt: skip
    make_ticket(client, title="Другое")
    assert len(client.get("/api/tickets", params={"q": "ерлан"}).json()) == 1
    assert len(client.get("/api/tickets", params={"q": "ПОЧТА"}).json()) == 1


def test_search_combines_with_filters(client):
    make_ticket(client, priority="P1", title="Сервер упал")
    make_ticket(client, priority="P3", title="Сервер медленный")
    resp = client.get("/api/tickets", params={"q": "сервер", "priority": "P1"})
    assert [t["title"] for t in resp.json()] == ["Сервер упал"]


def test_search_query_too_long(client):
    assert client.get("/api/tickets", params={"q": "x" * 101}).status_code == 422


def test_ui_search(client):
    make_ticket(client, title="Принтер не печатает")
    make_ticket(client, title="VPN disconnects")
    page = client.get("/", params={"q": "принтер", "lang": "ru"}).text
    assert "Принтер не печатает" in page
    assert "VPN disconnects" not in page
    assert "Найдено: 1" in page


def test_list_page_is_limited_and_shows_total(client, monkeypatch):
    monkeypatch.setattr("app.main.PAGE_SIZE", 3)
    for i in range(5):
        make_ticket(client, title=f"Ticket number {i}")
    page = client.get("/", params={"lang": "en"}).text
    assert page.count("Ticket number") == 3
    assert "Page 1 / 2" in page  # 5 tickets, 3 per page
    page2 = client.get("/", params={"lang": "en", "page": 2}).text
    assert page2.count("Ticket number") == 2
    assert 'aria-current="page">2<' in page2


def test_api_limit(client):
    for i in range(4):
        make_ticket(client, title=f"Limit test {i}")
    assert len(client.get("/api/tickets", params={"limit": 2}).json()) == 2
    assert client.get("/api/tickets", params={"limit": 0}).status_code == 422
    assert client.get("/api/tickets", params={"limit": 501}).status_code == 422


def test_search_count_is_total_not_page(client, monkeypatch):
    monkeypatch.setattr("app.main.PAGE_SIZE", 2)
    for i in range(3):
        make_ticket(client, title=f"Принтер {i}")
    page = client.get("/", params={"q": "принтер", "lang": "ru"}).text
    assert "Найдено: 3" in page


def test_database_uses_wal(client, tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "test.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


@pytest.mark.parametrize(
    "lang,heading", [("kk", "Басқару тақтасы"), ("ru", "Панель управления"), ("en", "Dashboard")]
)
def test_dashboard_page(client, lang, heading):
    make_ticket(client, priority="P1")
    page = client.get("/dashboard", params={"lang": lang})
    assert page.status_code == 200
    assert heading in page.text
    assert page.text.count('class="group"') == 14  # 7 days x (desktop + phone chart)


def test_dashboard_api(client):
    make_ticket(client, priority="P1")
    tid = make_ticket(client, priority="P3")["id"]
    for status in ("in_progress", "resolved"):
        client.post(f"/api/tickets/{tid}/status", json={"status": status})
    d = client.get("/api/dashboard").json()
    assert d["total"] == 2 and d["open"] == 1 and d["open_p1"] == 1
    assert d["days"][-1]["created"] == 2 and d["days"][-1]["resolved"] == 1
    assert d["sla_compliance"] == 100
    assert [t["priority"] for t in d["urgent"]] == ["P1"]


def test_index_summary(client):
    make_ticket(client, priority="P1")
    make_ticket(client, priority="P2")
    page = client.get("/", params={"lang": "en"}).text
    assert "Open P1" in page and "All tickets" in page


@pytest.mark.parametrize(
    "peak,axis",
    [
        (1, (1, 1)),
        (4, (1, 4)),
        (5, (1, 5)),
        (9, (2, 5)),
        (20, (5, 4)),
        (21, (5, 5)),
        (180, (50, 4)),
    ],
)
def test_nice_axis(peak, axis):
    from app.main import nice_axis

    step, count = nice_axis(peak)
    assert (step, count) == axis
    assert step * count >= peak and count <= 5


# ---------- comments, history, assignment ----------


def test_comment_and_history_api(client):
    tid = make_ticket(client)["id"]
    r = client.post(
        f"/api/tickets/{tid}/comments", json={"author": "Ерлан", "body": "Тексеріп жатырмын"}
    )
    assert r.status_code == 201 and r.json()["kind"] == "comment"
    client.post(f"/api/tickets/{tid}/assign", json={"assignee": "Ерлан"})
    client.post(f"/api/tickets/{tid}/status", json={"status": "in_progress", "author": "Ерлан"})
    kinds = [e["kind"] for e in client.get(f"/api/tickets/{tid}/events").json()]
    assert kinds == ["comment", "assigned", "status"]
    assert client.get("/api/assignees").json() == ["Ерлан"]
    assert client.get(f"/api/tickets/{tid}").json()["assignee"] == "Ерлан"


def test_comment_validation(client):
    tid = make_ticket(client)["id"]
    assert (
        client.post(f"/api/tickets/{tid}/comments", json={"author": "E", "body": "x"}).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/tickets/{tid}/comments", json={"author": "Ерлан", "body": ""}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/tickets/999/comments", json={"author": "Ерлан", "body": "x"}).status_code
        == 404
    )


def test_ticket_page_forms(client):
    tid = make_ticket(client)["id"]
    form = {"author": "Дана", "body": "<b>жоқ</b>", "lang": "ru"}
    r = client.post(f"/tickets/{tid}/comment", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/tickets/{tid}?lang=ru#history"
    client.post(f"/tickets/{tid}/assign", data={"assignee": "Дана", "lang": "ru"})
    page = client.get(f"/tickets/{tid}", params={"lang": "ru"}).text
    assert "История" in page and "Дана" in page
    assert "&lt;b&gt;жоқ&lt;/b&gt;" in page  # comment text is escaped, not rendered as HTML


def test_redirect_lang_cannot_be_injected(client):
    tid = make_ticket(client)["id"]
    r = client.post(f"/tickets/{tid}/assign", data={"assignee": "", "lang": "x\r\nSet-Cookie: a=b"},
                    follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == f"/tickets/{tid}?lang=kk"


# ---------- filters, sorting, pages ----------


def test_html_filters(client):
    a = make_ticket(client, priority="P1", title="Сервер құлады")["id"]
    make_ticket(client, priority="P3", title="Принтер")
    client.post(f"/api/tickets/{a}/assign", json={"assignee": "Ерлан"})
    page = client.get("/", params={"lang": "kk", "priority": "P1"}).text
    assert "Сервер құлады" in page and "Принтер" not in page
    page = client.get("/", params={"lang": "kk", "assignee": "__none__"}).text
    assert "Принтер" in page and "Сервер құлады" not in page
    # empty values from the form and garbage mean "no filter", not an error
    page = client.get("/", params={"status": "", "priority": "P9", "sort": "nope"})
    assert page.status_code == 200 and "Принтер" in page.text and "Сервер құлады" in page.text


def test_api_sort_and_offset(client):
    ids = [make_ticket(client, priority="P3", title=f"Ticket {i}")["id"] for i in range(3)]
    newest = client.get("/api/tickets", params={"sort": "newest", "limit": 1}).json()
    assert newest[0]["id"] == ids[-1]
    assert client.get("/api/tickets", params={"offset": 1, "limit": 5}).json()[0]["id"] == ids[1]
    assert client.get("/api/tickets", params={"sort": "nope"}).status_code == 422


def test_page_window():
    from app.main import page_window

    assert page_window(1, 1) == [1]
    assert page_window(1, 4) == [1, 2, 3, 4]
    assert page_window(10, 20) == [1, None, 8, 9, 10, 11, 12, None, 20]


# ---------- CSV export ----------


def test_csv_export(client):
    tid = make_ticket(client, priority="P1", title='=HYPERLINK("http://evil")')["id"]
    make_ticket(client, priority="P3", title="Принтер; 305 аудитория")
    client.post(f"/api/tickets/{tid}/assign", json={"assignee": "Ерлан"})
    r = client.get("/export.csv", params={"lang": "ru"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")  # BOM: Excel shows Cyrillic correctly
    rows = [line.split(";") for line in text.lstrip("﻿").splitlines()]
    assert rows[0][:3] == ["#", "Тема", "Заявитель"]
    assert len(rows) == 3
    assert "'=HYPERLINK" in text  # formula injection neutralised
    assert '"Принтер; 305 аудитория"' in text  # delimiter inside a value is quoted
    assert "Ерлан" in text
    assert "—" not in text  # empty dates stay empty cells for Excel


def test_csv_export_respects_filters(client):
    make_ticket(client, priority="P1", title="Only this one")
    make_ticket(client, priority="P4", title="Not this")
    text = client.get("/export.csv", params={"priority": "P1"}).content.decode("utf-8")
    assert "Only this one" in text and "Not this" not in text


def test_dashboard_shows_assignee_load(client):
    tid = make_ticket(client)["id"]
    client.post(f"/api/tickets/{tid}/assign", json={"assignee": "Ерлан"})
    make_ticket(client)
    d = client.get("/api/dashboard").json()
    assert d["by_assignee"] == [{"name": "Ерлан", "count": 1}, {"name": None, "count": 1}]
    assert "Ерлан" in client.get("/dashboard").text
