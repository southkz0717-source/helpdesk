from datetime import UTC, datetime

from app.timefmt import localtime, tz_label


def test_almaty_is_utc_plus_5(monkeypatch):
    monkeypatch.delenv("HELPDESK_TZ", raising=False)
    noon_utc = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    assert localtime(noon_utc) == "2026-11-17 17:00"
    assert tz_label() == "UTC+5"


def test_summer_time_is_also_utc_plus_5(monkeypatch):
    # Kazakhstan has no daylight saving time
    monkeypatch.delenv("HELPDESK_TZ", raising=False)
    assert localtime(datetime(2026, 7, 1, 0, 0, tzinfo=UTC)) == "2026-07-01 05:00"


def test_empty_value():
    assert localtime(None) == "—"


def test_zone_is_configurable(monkeypatch):
    monkeypatch.setenv("HELPDESK_TZ", "UTC")
    assert localtime(datetime(2026, 11, 17, 12, 0, tzinfo=UTC)) == "2026-11-17 12:00"
    assert tz_label() == "UTC"
