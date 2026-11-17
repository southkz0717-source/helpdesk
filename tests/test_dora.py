from datetime import UTC, datetime, timedelta

import httpx

from scripts.dora import GitHub, Incident, Release, collect, compute, render_dashboard

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
H = timedelta(hours=1)


def test_metrics_from_history():
    releases = [
        Release("v0.1.0", T0 + 24 * H, commit_times=[T0, T0 + 12 * H]),
        Release("v0.2.0", T0 + 7 * 24 * H, commit_times=[T0 + 6 * 24 * H]),
    ]
    incidents = [
        # opened after v0.2.0, fixed in 2 hours
        Incident(1, "500 on /tickets", T0 + 8 * 24 * H, T0 + 8 * 24 * H + 2 * H),
    ]
    m = compute(releases, incidents, T0, T0 + 14 * 24 * H)

    assert m.releases == 2
    assert m.deploys_per_week == 1.0
    assert m.lead_time_median_h == 24.0  # lead times: 24, 12, 24
    assert m.change_failure_rate == 0.5  # v0.2.0 caused the incident
    assert releases[1].incidents == 1 and releases[0].incidents == 0
    assert m.restore_median_h == 2.0
    assert m.levels == {
        "deployment_frequency": "High",
        "lead_time": "High",
        "change_failure_rate": "Low",
        "time_to_restore": "High",
    }


def test_no_data():
    m = compute([], [], T0, T0 + timedelta(days=3))
    assert m.releases == 0
    assert m.lead_time_median_h is None
    assert m.change_failure_rate is None
    assert m.levels["deployment_frequency"] == "Low"
    assert m.levels["lead_time"] == "n/a"


def test_open_incident_not_in_restore_time():
    releases = [Release("v1.0.0", T0)]
    incidents = [Incident(5, "Slow search", T0 + H, None)]
    m = compute(releases, incidents, T0, T0 + timedelta(days=7))
    assert m.open_incidents == 1
    assert m.restore_median_h is None
    assert m.change_failure_rate == 1.0


def commit(date: str) -> dict:
    return {"commit": {"author": {"date": date}}}


def fake_github(request: httpx.Request) -> httpx.Response:
    """Minimal fake of the GitHub REST API for repo 'kz/helpdesk'."""
    path, params = request.url.path, request.url.params
    if path == "/repos/kz/helpdesk":
        return httpx.Response(200, json={"created_at": "2026-11-02T09:00:00Z"})
    if path == "/repos/kz/helpdesk/releases":
        return httpx.Response(
            200,
            json=[
                {"tag_name": "v0.2.0", "published_at": "2026-11-09T09:00:00Z",
                 "draft": False, "prerelease": False},
                {"tag_name": "v0.1.0", "published_at": "2026-11-03T09:00:00Z",
                 "draft": False, "prerelease": False},
                {"tag_name": "v0.3.0-rc1", "published_at": "2026-11-10T09:00:00Z",
                 "draft": False, "prerelease": True},
            ],
        )  # fmt: skip
    if path == "/repos/kz/helpdesk/commits":
        assert params["sha"] == "v0.1.0" and params["since"].startswith("2026-11-02")
        if params.get("page") == "2":
            return httpx.Response(200, json=[commit("2026-11-02T21:00:00Z")])
        next_url = request.url.copy_merge_params({"page": "2"})  # GitHub keeps the query
        return httpx.Response(
            200,
            json=[commit("2026-11-02T09:00:00Z")],
            headers={"Link": f'<{next_url}>; rel="next"'},
        )
    if path == "/repos/kz/helpdesk/compare/v0.1.0...v0.2.0":
        return httpx.Response(200, json={"commits": [commit("2026-11-08T09:00:00Z")]})
    if path == "/repos/kz/helpdesk/issues":
        assert params["labels"] == "incident"
        return httpx.Response(
            200,
            json=[
                {"number": 7, "title": "500 error", "created_at": "2026-11-10T09:00:00Z",
                 "closed_at": "2026-11-10T10:30:00Z"},
                {"number": 8, "title": "a PR, not an issue", "created_at": "2026-11-10T09:00:00Z",
                 "closed_at": None, "pull_request": {}},
            ],
        )  # fmt: skip
    return httpx.Response(404, json={"message": f"unexpected {path}"})


def test_collect_from_github_api(tmp_path):
    gh = GitHub("kz/helpdesk", transport=httpx.MockTransport(fake_github))
    releases, incidents, m = collect(gh, datetime(2026, 11, 16, 9, 0, tzinfo=UTC))

    assert [r.tag for r in releases] == ["v0.1.0", "v0.2.0"]  # prerelease skipped, sorted
    assert len(releases[0].commit_times) == 2  # both pages were read
    assert [i.number for i in incidents] == [7]  # pull requests are ignored
    assert m.deploys_per_week == 1.0
    assert m.lead_time_median_h == 24.0  # lead times: 24, 12, 24
    assert m.change_failure_rate == 0.5
    assert m.restore_median_h == 1.5

    render_dashboard(releases, incidents, m, tmp_path / "dashboard.png")
    assert (tmp_path / "dashboard.png").stat().st_size > 10_000
