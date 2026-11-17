"""Display times in the users' time zone (Kazakhstan, UTC+5 since 2024).

Times are stored in UTC; only the HTML interface converts them.
The zone can be changed with the HELPDESK_TZ environment variable.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Almaty"


def display_tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("HELPDESK_TZ", DEFAULT_TZ))


def localtime(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Jinja filter: UTC datetime -> local time string, '—' for empty values."""
    if value is None:
        return "—"
    return value.astimezone(display_tz()).strftime(fmt)


def tz_label() -> str:
    """Short label for the interface, e.g. 'UTC+5'."""
    offset = datetime.now(display_tz()).utcoffset()
    hours = int(offset.total_seconds() // 3600)
    return f"UTC{hours:+d}" if hours else "UTC"
