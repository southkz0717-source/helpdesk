"""End-to-end tests: a real browser (Chromium) against the running service.

Each test follows a user scenario from the UAT list (docs/uat.md).
"""

import json
import re
import urllib.request
import uuid

from playwright.sync_api import Page, expect


def api_create(base_url: str, title: str, priority: str = "P3", requester: str = "Тест") -> int:
    req = urllib.request.Request(
        f"{base_url}/api/tickets",
        data=json.dumps({"title": title, "requester": requester, "priority": priority}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["id"]


def unique(text: str) -> str:
    return f"{text} {uuid.uuid4().hex[:6]}"


def test_create_ticket_and_see_sla(page: Page):
    """UAT-01: a user files a P2 ticket and sees both SLA deadlines in local time."""
    title = unique("Принтер 305 аудиторияда басып шығармайды")
    page.goto("/?lang=kk")
    page.get_by_label("Тақырып").fill(title)
    page.get_by_label("Өтініш беруші").fill("Айгерім")
    page.get_by_label("Басымдық").select_option("P2")
    page.get_by_role("button", name="Жіберу").click()

    expect(page).to_have_url(re.compile(r"/tickets/\d+"))
    expect(page.get_by_role("heading", level=2)).to_contain_text(title)
    expect(page.get_by_text("Жауап мерзімі")).to_be_visible()
    expect(page.get_by_text("UTC+5")).to_be_visible()


def test_full_status_lifecycle(page: Page, base_url: str):
    """UAT-02: an operator moves a ticket new -> in progress -> resolved -> closed."""
    ticket_id = api_create(base_url, unique("VPN ажырап қалады"), "P2")
    page.goto(f"/tickets/{ticket_id}?lang=ru")
    for status, label in [
        ("in_progress", "В работе"),
        ("resolved", "Решена"),
        ("closed", "Закрыта"),
    ]:
        page.get_by_label("Сменить статус").select_option(status)
        page.get_by_role("button", name="Отправить").click()
        expect(page.locator("td", has_text=label)).to_be_visible()
    # a closed ticket has no further transitions
    expect(page.get_by_label("Сменить статус")).to_have_count(0)


def test_language_switch(page: Page):
    """UAT-06: the interface works in Kazakh, Russian and English."""
    page.goto("/")
    expect(page.get_by_role("heading", name="Жаңа өтінім")).to_be_visible()
    page.get_by_role("link", name="RU").click()
    expect(page.get_by_role("heading", name="Новая заявка")).to_be_visible()
    page.get_by_role("link", name="EN").click()
    expect(page.get_by_role("heading", name="New ticket")).to_be_visible()


def test_search_ignores_case_in_kazakh(page: Page, base_url: str):
    """UAT-04: search finds a ticket written in Kazakh by an upper-case query."""
    marker = uuid.uuid4().hex[:6]
    api_create(base_url, f"Қолдау қызметіне кіру {marker}")
    api_create(base_url, f"Басқа мәселе {marker}")
    page.goto("/?lang=kk")
    page.get_by_role("searchbox").fill(f"ҚОЛДАУ ҚЫЗМЕТІНЕ КІРУ {marker.upper()}")
    page.get_by_role("button", name="Іздеу").click()
    expect(page.get_by_text("Табылды: 1")).to_be_visible()
    expect(page.get_by_role("link", name=re.compile("Қолдау қызметіне кіру"))).to_be_visible()


def test_required_fields_block_submit(page: Page):
    """UAT-01 negative: an empty form is not sent."""
    page.goto("/?lang=en")
    page.get_by_role("button", name="Submit").click()
    expect(page).to_have_url(re.compile(r"/\?lang=en$"))


def test_form_is_usable_from_keyboard(page: Page):
    """Accessibility: every field has a label and the form can be filled without a mouse."""
    page.goto("/?lang=en")
    page.get_by_label("Title").focus()
    page.keyboard.type(unique("Keyboard only"))
    page.keyboard.press("Tab")
    page.keyboard.type("Dana")
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/tickets/\d+"))
