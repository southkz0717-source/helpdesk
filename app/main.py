"""Helpdesk: ticket service with P1-P4 priorities and SLA deadlines."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from app import db
from app.dashboard import compute as compute_dashboard
from app.export import tickets_csv
from app.i18n import LANGUAGES, get_texts
from app.sla import Priority, Status, can_transition, is_breached
from app.storage import storage_status, warn_if_ephemeral
from app.timefmt import display_tz, localtime, tz_label

__version__ = "0.5.0"

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
TEMPLATES.env.filters["localtime"] = localtime
TEMPLATES.env.globals["tz_label"] = tz_label


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    warn_if_ephemeral()
    yield


app = FastAPI(title="Helpdesk", version=__version__, lifespan=lifespan)


# ---------- API models ----------


class TicketIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    requester: str = Field(min_length=2, max_length=100)
    priority: Priority


class StatusIn(BaseModel):
    status: Status
    author: str | None = Field(default=None, max_length=100)


class CommentIn(BaseModel):
    author: str = Field(min_length=2, max_length=100)
    body: str = Field(min_length=1, max_length=2000)


class AssignIn(BaseModel):
    assignee: str | None = Field(default=None, max_length=100, description="empty = unassign")
    author: str | None = Field(default=None, max_length=100)


Sort = Literal["queue", "newest", "oldest", "due"]


def with_sla_flags(ticket: dict) -> dict:
    now = db.now()
    ticket["response_breached"] = is_breached(
        ticket["response_due"], ticket["first_response_at"], now
    )
    ticket["resolve_breached"] = is_breached(ticket["resolve_due"], ticket["resolved_at"], now)
    return ticket


def get_or_404(ticket_id: int) -> dict:
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def change_status(ticket_id: int, new_status: Status, author: str | None = None) -> dict:
    ticket = get_or_404(ticket_id)
    current = Status(ticket["status"])
    if not can_transition(current, new_status):
        raise HTTPException(
            status_code=409,
            detail=f"Transition {current.value} -> {new_status.value} is not allowed",
        )
    return db.set_status(ticket_id, new_status, author)


def parse_enum(enum, value: str | None):
    """HTML filter forms send '' for 'any'; unknown values also mean 'no filter'."""
    try:
        return enum(value) if value else None
    except ValueError:
        return None


# ---------- JSON API ----------


@app.get("/health")
def health() -> dict:
    # persistent_storage: false means tickets will be lost on redeploy (incident, v0.3.0)
    return {"status": "ok", "version": __version__, "persistent_storage": storage_status()}


@app.post("/api/tickets", status_code=201)
def api_create_ticket(payload: TicketIn) -> dict:
    ticket = db.create_ticket(
        payload.title, payload.description, payload.requester, payload.priority
    )
    return with_sla_flags(ticket)


PAGE_SIZE = 50  # tickets shown on the list page

SearchQuery = Annotated[
    str | None, Query(max_length=100, description="Search in title, requester, description")
]


@app.get("/api/tickets")
def api_list_tickets(
    status: Status | None = None,
    priority: Priority | None = None,
    q: SearchQuery = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    assignee: Annotated[str | None, Query(max_length=100, description="name, or __none__")] = None,
    sort: Sort = "queue",
) -> list[dict]:
    tickets = db.list_tickets(
        status, priority, q, limit, assignee=assignee, sort=sort, offset=offset
    )
    return [with_sla_flags(t) for t in tickets]


@app.get("/api/tickets/{ticket_id}")
def api_get_ticket(ticket_id: int) -> dict:
    return with_sla_flags(get_or_404(ticket_id))


@app.post("/api/tickets/{ticket_id}/status")
def api_change_status(ticket_id: int, payload: StatusIn) -> dict:
    return with_sla_flags(change_status(ticket_id, payload.status, payload.author))


@app.get("/api/tickets/{ticket_id}/events")
def api_events(ticket_id: int) -> list[dict]:
    get_or_404(ticket_id)
    return db.list_events(ticket_id)


@app.post("/api/tickets/{ticket_id}/comments", status_code=201)
def api_add_comment(ticket_id: int, payload: CommentIn) -> dict:
    get_or_404(ticket_id)
    return db.add_comment(ticket_id, payload.author.strip(), payload.body.strip())


@app.post("/api/tickets/{ticket_id}/assign")
def api_assign(ticket_id: int, payload: AssignIn) -> dict:
    get_or_404(ticket_id)
    return with_sla_flags(db.assign(ticket_id, payload.assignee, payload.author))


@app.get("/api/assignees")
def api_assignees() -> list[str]:
    return db.list_assignees()


@app.get("/api/stats")
def api_stats() -> dict:
    tickets = [with_sla_flags(t) for t in db.list_tickets()]
    open_tickets = [t for t in tickets if t["status"] in (Status.NEW, Status.IN_PROGRESS)]
    return {
        "total": len(tickets),
        "open_by_priority": {
            p.value: sum(t["priority"] == p for t in open_tickets) for p in Priority
        },
        "sla_breached": sum(t["response_breached"] or t["resolve_breached"] for t in tickets),
    }


# ---------- HTML UI ----------


def render(request: Request, name: str, lang: str | None, **context) -> HTMLResponse:
    lang, texts = get_texts(lang)
    base = {"lang": lang, "t": texts, "languages": LANGUAGES, "priorities": list(Priority)}
    return TEMPLATES.TemplateResponse(request, name, {**base, **context})


def dashboard_data() -> dict:
    tickets = [with_sla_flags(t) for t in db.list_tickets()]
    return compute_dashboard(tickets, db.now(), display_tz())


def nice_axis(peak: int, max_ticks: int = 5) -> tuple[int, int]:
    """(step, number of steps) for a value axis: step is 1, 2, 5, 10, 20, 50, ...

    Picks the smallest step that covers `peak` in at most `max_ticks` steps, so the
    axis ends just above the data (peak 9 -> 0..10 by 2, not 0..20 by 5).
    """
    magnitude = 1
    while True:
        for m in (1, 2, 5):
            step = m * magnitude
            count = max(1, -(-peak // step))  # ceil
            if count <= max_ticks:
                return step, count
        magnitude *= 10


def bar_chart(days: list[dict], width: int = 640, height: int = 240) -> dict:
    """Geometry of the grouped bar chart (created vs resolved per day) for the SVG template."""
    left, right, top, bottom = 34, 8, 14, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max([1] + [max(d["created"], d["resolved"]) for d in days])
    step, count = nice_axis(peak)
    axis_max = step * count
    group_w = plot_w / len(days)
    bar_w = min(18, group_w / 2 - 6)
    gap = 2  # surface gap between the two bars of a day

    def y(v: float) -> float:
        return top + plot_h - plot_h * v / axis_max

    groups = []
    for i, d in enumerate(days):
        cx = left + group_w * i + group_w / 2
        groups.append({
            **d,
            "label": d["date"][8:10] + "." + d["date"][5:7],
            "cx": round(cx, 1),
            "x": round(left + group_w * i, 1),
            "w": round(group_w, 1),
            "bars": [
                {"series": 1, "value": d["created"], "x": round(cx - gap / 2 - bar_w, 1),
                 "y": round(y(d["created"]), 1), "h": round(top + plot_h - y(d["created"]), 1)},
                {"series": 2, "value": d["resolved"], "x": round(cx + gap / 2, 1),
                 "y": round(y(d["resolved"]), 1), "h": round(top + plot_h - y(d["resolved"]), 1)},
            ],
        })  # fmt: skip
    ticks = [{"value": step * k, "y": round(y(step * k), 1)} for k in range(count + 1)]
    return {"width": width, "height": height, "left": left, "right": width - right,
            "top": top, "base": top + plot_h, "bar_w": round(bar_w, 1), "groups": groups,
            "ticks": ticks}  # fmt: skip


@app.get("/api/dashboard")
def api_dashboard() -> dict:
    return dashboard_data()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, lang: str | None = None) -> HTMLResponse:
    data = dashboard_data()
    return render(
        request, "dashboard.html", lang, page="dashboard", d=data, chart=bar_chart(data["days"]),
        chart_sm=bar_chart(data["days"], width=360, height=230),
        updated=db.now(),
    )  # fmt: skip


FILTER_SORTS = ("queue", "newest", "oldest", "due")


def list_filters(status, priority, assignee, sort, q) -> dict:
    """Normalised filters for the list page and CSV export (empty = no filter)."""
    return {
        "status": parse_enum(Status, status),
        "priority": parse_enum(Priority, priority),
        "assignee": (assignee or "").strip()[:100] or None,
        "sort": sort if sort in FILTER_SORTS else "queue",
        "q": (q or "").strip()[:100] or None,
    }


def filter_query(f: dict, lang: str, **extra) -> str:
    """Query string that keeps the current filters (for pages, CSV link, reset)."""
    from urllib.parse import urlencode

    params = {"lang": lang, "q": f["q"], "status": f["status"] and f["status"].value,
              "priority": f["priority"] and f["priority"].value, "assignee": f["assignee"],
              "sort": None if f["sort"] == "queue" else f["sort"], **extra}  # fmt: skip
    return urlencode({k: v for k, v in params.items() if v})


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    lang: str | None = None,
    q: SearchQuery = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: Annotated[str | None, Query(max_length=100)] = None,
    sort: str | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> HTMLResponse:
    f = list_filters(status, priority, assignee, sort, q)
    total = db.count_tickets(f["status"], f["priority"], f["q"], assignee=f["assignee"])
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(page, pages)
    tickets = db.list_tickets(
        f["status"], f["priority"], f["q"], PAGE_SIZE,
        assignee=f["assignee"], sort=f["sort"], offset=(page - 1) * PAGE_SIZE,
    )  # fmt: skip
    summary = {
        "total": db.count_tickets(),
        "open": db.count_tickets(Status.NEW) + db.count_tickets(Status.IN_PROGRESS),
        "open_p1": db.count_tickets(Status.NEW, Priority.P1)
        + db.count_tickets(Status.IN_PROGRESS, Priority.P1),
    }
    lang_code, _ = get_texts(lang)
    filtered = any(f[k] for k in ("status", "priority", "assignee")) or f["sort"] != "queue"
    return render(
        request, "index.html", lang, page="tickets", tickets=[with_sla_flags(t) for t in tickets],
        total=total, q=f["q"] or "", f=f, filtered=filtered, summary=summary,
        page_no=page, pages=pages, page_window=page_window(page, pages),
        assignees=db.list_assignees(), unassigned=db.UNASSIGNED,
        qs=lambda **extra: filter_query(f, lang_code, **extra),
    )  # fmt: skip


def page_window(page: int, pages: int) -> list[int | None]:
    """Page numbers to show: first, last and two around the current one; None = gap."""
    wanted = {1, pages, page - 2, page - 1, page, page + 1, page + 2}
    shown = sorted(n for n in wanted if 1 <= n <= pages)
    out: list[int | None] = []
    for n in shown:
        if out and n - out[-1] > 1:
            out.append(None)
        out.append(n)
    return out


@app.get("/export.csv")
def export_csv(
    lang: str | None = None,
    q: SearchQuery = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: Annotated[str | None, Query(max_length=100)] = None,
    sort: str | None = None,
) -> Response:
    f = list_filters(status, priority, assignee, sort, q)
    tickets = db.list_tickets(
        f["status"], f["priority"], f["q"], assignee=f["assignee"], sort=f["sort"]
    )
    _, texts = get_texts(lang)
    # empty cell, not '—', so Excel can sort and filter the date columns
    body = tickets_csv(
        [with_sla_flags(t) for t in tickets], texts, lambda d: localtime(d) if d else ""
    )
    name = f"helpdesk-{db.now().astimezone(display_tz()):%Y%m%d-%H%M}.csv"
    return Response(
        body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )  # fmt: skip


@app.post("/tickets")
def form_create_ticket(
    title: str = Form(...),
    requester: str = Form(...),
    priority: Priority = Form(...),
    description: str = Form(""),
    lang: str = Form("kk"),
) -> RedirectResponse:
    try:
        payload = TicketIn(
            title=title, description=description, requester=requester, priority=priority
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    ticket = db.create_ticket(
        payload.title, payload.description, payload.requester, payload.priority
    )
    return back_to_ticket(ticket["id"], lang)


def back_to_ticket(ticket_id: int, lang: str | None, anchor: str = "") -> RedirectResponse:
    lang, _ = get_texts(lang)  # only kk/ru/en can end up in the URL
    return RedirectResponse(f"/tickets/{ticket_id}?lang={lang}{anchor}", status_code=303)


@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_page(request: Request, ticket_id: int, lang: str | None = None) -> HTMLResponse:
    ticket = with_sla_flags(get_or_404(ticket_id))
    allowed = sorted(s.value for s in Status if can_transition(Status(ticket["status"]), s))
    return render(
        request, "ticket.html", lang, page="tickets", ticket=ticket, allowed=allowed,
        events=db.list_events(ticket_id), assignees=db.list_assignees(),
    )  # fmt: skip


@app.post("/tickets/{ticket_id}/status")
def form_change_status(
    ticket_id: int, status: Status = Form(...), lang: str = Form("kk")
) -> RedirectResponse:
    change_status(ticket_id, status)
    return back_to_ticket(ticket_id, lang)


@app.post("/tickets/{ticket_id}/comment")
def form_add_comment(
    ticket_id: int, author: str = Form(...), body: str = Form(...), lang: str = Form("kk")
) -> RedirectResponse:
    get_or_404(ticket_id)
    try:
        payload = CommentIn(author=author.strip(), body=body.strip())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    db.add_comment(ticket_id, payload.author, payload.body)
    return back_to_ticket(ticket_id, lang, "#history")


@app.post("/tickets/{ticket_id}/assign")
def form_assign(
    ticket_id: int, assignee: str = Form(""), lang: str = Form("kk")
) -> RedirectResponse:
    get_or_404(ticket_id)
    if len(assignee) > 100:
        raise HTTPException(status_code=422, detail="assignee is too long")
    db.assign(ticket_id, assignee)
    return back_to_ticket(ticket_id, lang)
