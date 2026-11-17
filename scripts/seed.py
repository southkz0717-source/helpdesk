"""Fill a database with realistic synthetic tickets for the UAT / demo stand.

Ten records hide performance and usability problems; the stand needs a realistic
volume (docs/test-strategy.md, section 3). All data is synthetic: no real people.

Usage:
    HELPDESK_DB=stand.db python -m scripts.seed --count 200
        writes straight into a SQLite file, with creation dates spread over the last
        30 days (so some tickets already breach their SLA)
    python -m scripts.seed --url http://localhost:8000 --count 200
        fills a RUNNING stand (e.g. the Docker one) through the public API;
        tickets get the current time, statuses go through the allowed transitions

The same --seed gives the same data, so UAT participants see the same tickets.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import urllib.request
from datetime import UTC, datetime, timedelta

from app import db
from app.sla import Priority, Status, due_dates

PROBLEMS = [
    ("Принтер {room} аудиторияда басып шығармайды", "Қағаз бар, бірақ құжат кезекте тұрып қалады"),
    ("Wi-Fi {room} аудиторияда жоқ", "Желі көрінеді, бірақ қосылмайды"),
    ("Не открывается корпоративная почта", "Пишет «неверный пароль», хотя пароль верный"),
    ("Проектор в {room} не показывает изображение", "Ноутбук подключён через HDMI"),
    ("Platonus жүйесіне кіре алмаймын", "Логин мен құпиясөз дұрыс, бет жүктелмейді"),
    ("VPN отключается каждые 10 минут", "Работаю из дома, нужен доступ к библиотеке"),
    ("Компьютерге Office орнату керек", "Жаңа қызметкер, лицензия бар"),
    ("Құпиясөзді қалпына келтіру", "Құпиясөзді ұмыттым, телефон нөмірі өзгерген"),
    ("Moodle-да тапсырма жүктелмейді", "Файл 15 МБ, қате шығады"),
    ("Сломалась мышь и клавиатура в {room}", "Компьютерный класс, место 12"),
    ("Сервер журнала оценок недоступен", "Ошибка 502 у всех преподавателей кафедры"),
    ("Кафедраға жаңа ноутбук керек", "Ескісі 2016 жылғы, баяу жұмыс істейді"),
]
NAMES = [
    "Айгерім Н.", "Ерлан Т.", "Дана С.", "Нұрлан А.", "Мадина К.", "Асқар Б.", "Әсел Ж.",
    "Тимур Р.", "Жанар О.", "Бауыржан М.", "Ольга П.", "Сергей В.", "Гүлнар Е.", "Арман Қ.",
]  # fmt: skip
ROOMS = ["101", "204", "305", "312", "407", "А-12", "Б-3"]
# priority mix of a real support desk: few P1, most P3
PRIORITY_WEIGHTS = {Priority.P1: 5, Priority.P2: 20, Priority.P3: 55, Priority.P4: 20}
STATUS_WEIGHTS = {Status.NEW: 25, Status.IN_PROGRESS: 25, Status.RESOLVED: 20, Status.CLOSED: 30}


def seed(count: int, rng: random.Random, now: datetime) -> int:
    db.init_db()
    rows = []
    for _ in range(count):
        title, description = rng.choice(PROBLEMS)
        room = rng.choice(ROOMS)
        priority = rng.choices(list(PRIORITY_WEIGHTS), weights=PRIORITY_WEIGHTS.values())[0]
        status = rng.choices(list(STATUS_WEIGHTS), weights=STATUS_WEIGHTS.values())[0]
        created = now - timedelta(minutes=rng.randint(10, 60 * 24 * 30))
        response_due, resolve_due = due_dates(priority, created)
        first_response = resolved = None
        if status != Status.NEW:
            first_response = created + timedelta(minutes=rng.randint(5, 600))
        if status in (Status.RESOLVED, Status.CLOSED):
            resolved = first_response + timedelta(minutes=rng.randint(30, 60 * 24 * 5))
        rows.append(
            (
                title.format(room=room),
                description,
                rng.choice(NAMES),
                priority.value,
                status.value,
                *(d.isoformat() if d else None for d in (created, response_due, resolve_due)),
                *(d.isoformat() if d else None for d in (first_response, resolved)),
            )
        )
    with sqlite3.connect(db.db_path()) as conn:
        conn.executemany(
            "INSERT INTO tickets (title, description, requester, priority, status, created_at,"
            " response_due, resolve_due, first_response_at, resolved_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def seed_via_api(url: str, count: int, rng: random.Random) -> int:
    """Create tickets through the HTTP API of a running service."""
    # On Windows "localhost" resolves to IPv6 ::1 first; uvicorn listens on IPv4 only,
    # so every new connection waited ~2 s for the fallback (measured: 2.05 s vs 0.14 s).
    url = url.replace("://localhost", "://127.0.0.1")
    path = {Status.IN_PROGRESS: ["in_progress"], Status.RESOLVED: ["in_progress", "resolved"],
            Status.CLOSED: ["in_progress", "resolved", "closed"], Status.NEW: []}  # fmt: skip

    def post(endpoint: str, payload: dict) -> dict:
        req = urllib.request.Request(
            url.rstrip("/") + endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)

    for _ in range(count):
        title, description = rng.choice(PROBLEMS)
        priority = rng.choices(list(PRIORITY_WEIGHTS), weights=PRIORITY_WEIGHTS.values())[0]
        status = rng.choices(list(STATUS_WEIGHTS), weights=STATUS_WEIGHTS.values())[0]
        ticket = post(
            "/api/tickets",
            {"title": title.format(room=rng.choice(ROOMS)), "description": description,
             "requester": rng.choice(NAMES), "priority": priority.value},
        )  # fmt: skip
        for step in path[status]:
            post(f"/api/tickets/{ticket['id']}/status", {"status": step})
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic tickets for the demo stand")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--url", help="fill a running service through its API instead of a file")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    if args.url:
        added = seed_via_api(args.url, args.count, rng)
        print(f"{added} tickets added to {args.url}")
    else:
        added = seed(args.count, rng, datetime.now(UTC))
        print(f"{added} tickets added to {db.db_path()}")


if __name__ == "__main__":
    main()
