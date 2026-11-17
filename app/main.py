"""Helpdesk: ticket service with P1-P4 priorities and SLA deadlines."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from app import db
from app.i18n import LANGUAGES, get_texts
from app.sla import Priority, Status, can_transition, is_breached
from app.storage import storage_status, warn_if_ephemeral
from app.timefmt import localtime, tz_label

__version__ = "0.4.0"

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


def change_status(ticket_id: int, new_status: Status) -> dict:
    ticket = get_or_404(ticket_id)
    current = Status(ticket["status"])
    if not can_transition(current, new_status):
        raise HTTPException(
            status_code=409,
            detail=f"Transition {current.value} -> {new_status.value} is not allowed",
        )
    return db.set_status(ticket_id, new_status)


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
) -> list[dict]:
    return [with_sla_flags(t) for t in db.list_tickets(status, priority, q, limit)]


@app.get("/api/tickets/{ticket_id}")
def api_get_ticket(ticket_id: int) -> dict:
    return with_sla_flags(get_or_404(ticket_id))


@app.post("/api/tickets/{ticket_id}/status")
def api_change_status(ticket_id: int, payload: StatusIn) -> dict:
    return with_sla_flags(change_status(ticket_id, payload.status))


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
    return TEMPLATES.TemplateResponse(
        request,
        name,
        {"lang": lang, "t": texts, "languages": LANGUAGES, "priorities": list(Priority), **context},
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, lang: str | None = None, q: SearchQuery = None) -> HTMLResponse:
    tickets = [with_sla_flags(t) for t in db.list_tickets(q=q, limit=PAGE_SIZE)]
    total = db.count_tickets(q=q)
    return render(request, "index.html", lang, tickets=tickets, total=total, q=(q or "").strip())


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
    return RedirectResponse(f"/tickets/{ticket['id']}?lang={lang}", status_code=303)


@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_page(request: Request, ticket_id: int, lang: str | None = None) -> HTMLResponse:
    ticket = with_sla_flags(get_or_404(ticket_id))
    allowed = sorted(s.value for s in Status if can_transition(Status(ticket["status"]), s))
    return render(request, "ticket.html", lang, ticket=ticket, allowed=allowed)


@app.post("/tickets/{ticket_id}/status")
def form_change_status(
    ticket_id: int, status: Status = Form(...), lang: str = Form("kk")
) -> RedirectResponse:
    change_status(ticket_id, status)
    return RedirectResponse(f"/tickets/{ticket_id}?lang={lang}", status_code=303)
