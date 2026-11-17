"""DORA metrics dashboard built from the GitHub history of this repository.

Definitions used in the project (see docs/dora.md):
- Deployment: a published GitHub Release. release.yml creates one for every vX.Y.Z tag.
- Lead time for changes: release time minus author time of every commit shipped in that release.
- Change failure rate: share of releases that caused at least one incident.
  An incident is an issue with the label "incident"; it is attributed to the latest
  release published before the issue was opened.
- Time to restore service: incident issue closed_at minus created_at.

Usage:
    python scripts/dora.py --repo OWNER/NAME [--out docs/dora]
A token in GITHUB_TOKEN raises the API limit (60 -> 5000 requests per hour).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

API = "https://api.github.com"
INCIDENT_LABEL = "incident"


# ---------------------------------------------------------------- data model


@dataclass
class Release:
    tag: str
    published_at: datetime
    commit_times: list[datetime] = field(default_factory=list)
    incidents: int = 0

    @property
    def lead_times_h(self) -> list[float]:
        return [(self.published_at - t).total_seconds() / 3600 for t in self.commit_times]


@dataclass
class Incident:
    number: int
    title: str
    created_at: datetime
    closed_at: datetime | None

    @property
    def restore_h(self) -> float | None:
        if self.closed_at is None:
            return None
        return (self.closed_at - self.created_at).total_seconds() / 3600


@dataclass
class Metrics:
    period_start: datetime
    period_end: datetime
    releases: int
    deploys_per_week: float
    lead_time_median_h: float | None
    change_failure_rate: float | None
    restore_median_h: float | None
    open_incidents: int
    levels: dict[str, str]


# ---------------------------------------------------------------- GitHub API


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHub:
    def __init__(
        self, repo: str, token: str | None = None, transport: httpx.BaseTransport | None = None
    ):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.repo = repo
        self._created_at: datetime | None = None
        self.http = httpx.Client(base_url=API, headers=headers, timeout=30, transport=transport)

    def get(self, path: str, **params) -> dict | list:
        resp = self.http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def paginate(self, path: str, **params) -> list:
        items: list = []
        resp = self.http.get(path, params={"per_page": 100, **params})
        while True:
            resp.raise_for_status()
            items.extend(resp.json())
            next_url = resp.links.get("next", {}).get("url")
            if not next_url:
                break
            # the "next" link already carries the full query string; passing params
            # (even an empty dict) would make httpx replace it
            resp = self.http.get(next_url)
        return items

    def releases(self) -> list[Release]:
        raw = self.paginate(f"/repos/{self.repo}/releases")
        releases = [
            Release(tag=r["tag_name"], published_at=parse_time(r["published_at"]))
            for r in raw
            if not r["draft"] and not r["prerelease"] and r["published_at"]
        ]
        releases.sort(key=lambda r: r.published_at)
        previous: str | None = None
        for rel in releases:
            if previous:
                data = self.get(f"/repos/{self.repo}/compare/{previous}...{rel.tag}")
                commits = data["commits"]
            else:
                # first release: everything committed since the repository was created
                commits = self.paginate(
                    f"/repos/{self.repo}/commits", sha=rel.tag, since=self.created_at().isoformat()
                )
            rel.commit_times = [parse_time(c["commit"]["author"]["date"]) for c in commits]
            previous = rel.tag
        return releases

    def incidents(self) -> list[Incident]:
        raw = self.paginate(f"/repos/{self.repo}/issues", labels=INCIDENT_LABEL, state="all")
        return [
            Incident(
                number=i["number"],
                title=i["title"],
                created_at=parse_time(i["created_at"]),
                closed_at=parse_time(i["closed_at"]) if i["closed_at"] else None,
            )
            for i in raw
            if "pull_request" not in i
        ]

    def created_at(self) -> datetime:
        if self._created_at is None:
            self._created_at = parse_time(self.get(f"/repos/{self.repo}")["created_at"])
        return self._created_at


# ---------------------------------------------------------------- metrics


def attribute_incidents(releases: list[Release], incidents: list[Incident]) -> None:
    """Link every incident to the latest release published before it was opened."""
    for inc in incidents:
        before = [r for r in releases if r.published_at <= inc.created_at]
        if before:
            before[-1].incidents += 1


def level_deploy_frequency(per_week: float) -> str:
    if per_week >= 7:
        return "Elite"
    if per_week >= 1:
        return "High"
    if per_week >= 0.25:
        return "Medium"
    return "Low"


def level_lead_time(hours: float | None) -> str:
    if hours is None:
        return "n/a"
    if hours < 24:
        return "Elite"
    if hours < 24 * 7:
        return "High"
    if hours < 24 * 30:
        return "Medium"
    return "Low"


def level_change_failure(rate: float | None) -> str:
    if rate is None:
        return "n/a"
    if rate <= 0.05:
        return "Elite"
    if rate <= 0.10:
        return "High"
    if rate <= 0.15:
        return "Medium"
    return "Low"


def level_restore(hours: float | None) -> str:
    if hours is None:
        return "n/a"
    if hours < 1:
        return "Elite"
    if hours < 24:
        return "High"
    if hours < 24 * 7:
        return "Medium"
    return "Low"


def compute(
    releases: list[Release],
    incidents: list[Incident],
    period_start: datetime,
    period_end: datetime,
) -> Metrics:
    attribute_incidents(releases, incidents)
    weeks = max((period_end - period_start) / timedelta(weeks=1), 1.0)
    per_week = len(releases) / weeks

    lead_times = [h for r in releases for h in r.lead_times_h]
    lead_median = statistics.median(lead_times) if lead_times else None

    cfr = sum(r.incidents > 0 for r in releases) / len(releases) if releases else None

    restore = [i.restore_h for i in incidents if i.restore_h is not None]
    restore_median = statistics.median(restore) if restore else None

    return Metrics(
        period_start=period_start,
        period_end=period_end,
        releases=len(releases),
        deploys_per_week=per_week,
        lead_time_median_h=lead_median,
        change_failure_rate=cfr,
        restore_median_h=restore_median,
        open_incidents=sum(i.closed_at is None for i in incidents),
        levels={
            "deployment_frequency": level_deploy_frequency(per_week),
            "lead_time": level_lead_time(lead_median),
            "change_failure_rate": level_change_failure(cfr),
            "time_to_restore": level_restore(restore_median),
        },
    )


# ---------------------------------------------------------------- output


def fmt_hours(hours: float | None) -> str:
    if hours is None:
        return "деректер жоқ"
    if hours < 1:
        return f"{hours * 60:.0f} мин"
    if hours < 48:
        return f"{hours:.1f} сағ"
    return f"{hours / 24:.1f} күн"


def fmt_rate(rate: float | None) -> str:
    return "деректер жоқ" if rate is None else f"{rate:.0%}"


def render_dashboard(releases, incidents, metrics: Metrics, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    fig.suptitle(
        f"DORA · {metrics.period_start:%Y-%m-%d} — {metrics.period_end:%Y-%m-%d}",
        fontsize=14,
        fontweight="bold",
    )
    color, bad = "#0969da", "#cf222e"

    def empty(ax, title):
        ax.set_title(title)
        ax.text(0.5, 0.5, "деректер жоқ", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])

    # 1. Deployment frequency: releases per ISO week
    ax = axes[0][0]
    title = (
        f"Жаю жиілігі: {metrics.deploys_per_week:.2f} / апта "
        f"[{metrics.levels['deployment_frequency']}]"
    )
    if releases:
        weeks: dict[str, int] = {}
        cursor = metrics.period_start
        while cursor <= metrics.period_end:
            weeks[f"{cursor:%G-W%V}"] = 0
            cursor += timedelta(weeks=1)
        for r in releases:
            weeks[f"{r.published_at:%G-W%V}"] = weeks.get(f"{r.published_at:%G-W%V}", 0) + 1
        ax.bar(list(weeks), list(weeks.values()), color=color)
        ax.set_title(title)
        ax.set_ylabel("релиздер")
        ax.yaxis.get_major_locator().set_params(integer=True)
        ax.tick_params(axis="x", rotation=45, labelsize=8)
    else:
        empty(ax, title)

    # 2. Lead time for changes: median per release
    ax = axes[0][1]
    title = (
        f"Коммиттен продқа дейін: медиана {fmt_hours(metrics.lead_time_median_h)} "
        f"[{metrics.levels['lead_time']}]"
    )
    with_commits = [r for r in releases if r.commit_times]
    if with_commits:
        ax.bar(
            [r.tag for r in with_commits],
            [statistics.median(r.lead_times_h) for r in with_commits],
            color=color,
        )
        ax.set_title(title)
        ax.set_ylabel("сағат (медиана)")
        ax.tick_params(axis="x", rotation=45, labelsize=8)
    else:
        empty(ax, title)

    # 3. Change failure rate: incidents per release
    ax = axes[1][0]
    title = (
        f"Сәтсіз өзгерістер үлесі: {fmt_rate(metrics.change_failure_rate)} "
        f"[{metrics.levels['change_failure_rate']}]"
    )
    if releases:
        ax.bar(
            [r.tag for r in releases],
            [r.incidents for r in releases],
            color=[bad if r.incidents else color for r in releases],
        )
        ax.set_title(title)
        ax.set_ylabel("инциденттер")
        ax.yaxis.get_major_locator().set_params(integer=True)
        ax.tick_params(axis="x", rotation=45, labelsize=8)
    else:
        empty(ax, title)

    # 4. Time to restore service: per incident
    ax = axes[1][1]
    title = (
        f"Қалпына келу уақыты: медиана {fmt_hours(metrics.restore_median_h)} "
        f"[{metrics.levels['time_to_restore']}]"
    )
    closed = [i for i in incidents if i.restore_h is not None]
    if closed:
        ax.bar([f"#{i.number}" for i in closed], [i.restore_h for i in closed], color=bad)
        ax.set_title(title)
        ax.set_ylabel("сағат")
    else:
        empty(ax, title)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def render_report(metrics: Metrics, repo: str, path: Path) -> None:
    rows = [
        ("Жаю жиілігі (Deployment frequency)", f"{metrics.deploys_per_week:.2f} релиз / апта",
         metrics.levels["deployment_frequency"]),
        ("Коммиттен продқа дейінгі уақыт (Lead time)", fmt_hours(metrics.lead_time_median_h),
         metrics.levels["lead_time"]),
        ("Сәтсіз өзгерістер үлесі (Change failure rate)", fmt_rate(metrics.change_failure_rate),
         metrics.levels["change_failure_rate"]),
        ("Қалпына келу уақыты (Time to restore)", fmt_hours(metrics.restore_median_h),
         metrics.levels["time_to_restore"]),
    ]  # fmt: skip
    lines = [
        f"# DORA метрикалары — {repo}",
        "",
        f"Кезең: {metrics.period_start:%Y-%m-%d} — {metrics.period_end:%Y-%m-%d}. "
        f"Релиздер: {metrics.releases}. Ашық инциденттер: {metrics.open_incidents}.",
        f"Есептелген уақыты: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.",
        "",
        "| Метрика | Мәні | Деңгей |",
        "|---|---|---|",
        *[f"| {name} | {value} | {level} |" for name, value, level in rows],
        "",
        "![DORA dashboard](dashboard.png)",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def collect(gh: GitHub, now: datetime) -> tuple[list[Release], list[Incident], Metrics]:
    releases = gh.releases()
    incidents = gh.incidents()
    metrics = compute(releases, incidents, gh.created_at(), now)
    return releases, incidents, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), required=False)
    parser.add_argument("--out", default="docs/dora", type=Path)
    args = parser.parse_args()
    if not args.repo:
        parser.error("--repo OWNER/NAME is required (or set GITHUB_REPOSITORY)")

    gh = GitHub(args.repo, os.environ.get("GITHUB_TOKEN"))
    releases, incidents, metrics = collect(gh, datetime.now(UTC))

    args.out.mkdir(parents=True, exist_ok=True)
    data = {
        "repo": args.repo,
        "metrics": asdict(metrics),
        "releases": [asdict(r) | {"lead_times_h": r.lead_times_h} for r in releases],
        "incidents": [asdict(i) | {"restore_h": i.restore_h} for i in incidents],
    }
    (args.out / "data.json").write_text(
        json.dumps(data, default=str, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    render_dashboard(releases, incidents, metrics, args.out / "dashboard.png")
    render_report(metrics, args.repo, args.out / "report.md")
    print((args.out / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
