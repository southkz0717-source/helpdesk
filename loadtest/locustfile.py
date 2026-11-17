"""Load profile for Helpdesk (docs/test-strategy.md, section 5).

Profile: support-desk users mostly read the list and search, some create tickets,
operators change statuses.  Weights below are the share of requests:

    list page        40%   GET /
    search           20%   GET /api/tickets?q=...
    open a ticket    15%   GET /api/tickets/{id}
    create a ticket  15%   POST /api/tickets
    change status    10%   POST /api/tickets/{id}/status

Target: 200 concurrent users, p95 < 800 ms, errors < 1%.

Run (headless, 2 minutes, report in loadtest/report.html):
    locust -f loadtest/locustfile.py --host http://localhost:8000 \
        --headless -u 200 -r 20 -t 2m --html loadtest/report.html
"""

import random

from locust import HttpUser, between, events, task

QUERIES = ["принтер", "VPN", "қолдау", "пошта", "сервер", "құпиясөз"]
TITLES = [
    "Принтер басып шығармайды",
    "VPN ажырап қалады",
    "Почта не открывается",
    "Құпиясөзді қалпына келтіру",
    "Сервер медленно отвечает",
]
P95_TARGET_MS = 800
ERROR_TARGET = 0.01


class SupportUser(HttpUser):
    wait_time = between(1, 3)  # think time of a real user between actions

    def on_start(self):
        self.ticket_ids: list[int] = []
        self.create_ticket()

    @task(40)
    def list_page(self):
        self.client.get("/", name="GET /")

    @task(20)
    def search(self):
        self.client.get("/api/tickets", params={"q": random.choice(QUERIES)}, name="GET search")

    @task(15)
    def open_ticket(self):
        if self.ticket_ids:
            tid = random.choice(self.ticket_ids)
            self.client.get(f"/api/tickets/{tid}", name="GET /api/tickets/{id}")

    @task(15)
    def create_ticket(self):
        resp = self.client.post(
            "/api/tickets",
            json={
                "title": random.choice(TITLES),
                "requester": f"load-user-{random.randint(1, 500)}",
                "priority": random.choice(["P1", "P2", "P3", "P3", "P4"]),
            },
            name="POST /api/tickets",
        )
        if resp.status_code == 201:
            self.ticket_ids.append(resp.json()["id"])

    @task(10)
    def change_status(self):
        if self.ticket_ids:
            tid = self.ticket_ids.pop(0)
            self.client.post(
                f"/api/tickets/{tid}/status",
                json={"status": "in_progress"},
                name="POST /api/tickets/{id}/status",
            )


@events.quitting.add_listener
def check_targets(environment, **_):
    """Fail the run (exit code 1) when the targets from the test strategy are missed."""
    total = environment.stats.total
    p95 = total.get_response_time_percentile(0.95)
    error_rate = total.fail_ratio
    ok = p95 is not None and p95 < P95_TARGET_MS and error_rate < ERROR_TARGET
    print(
        f"\nTARGET p95 < {P95_TARGET_MS} ms: {p95} ms | errors < {ERROR_TARGET:.0%}: "
        f"{error_rate:.2%} -> {'PASS' if ok else 'FAIL'}"
    )
    if not ok:
        environment.process_exit_code = 1
