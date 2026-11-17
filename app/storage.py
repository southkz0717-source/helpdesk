"""Check that the SQLite file lives on persistent storage.

Incident (v0.3.0): when the container was started without a volume,
every redeploy created a fresh /data directory and all tickets were lost.
The service now reports whether its data directory is a mount point,
logs a warning at startup and shows it in /health, so monitoring can alert on it.
"""

import logging
import os
import posixpath
from pathlib import Path, PurePosixPath

from app.db import db_path

log = logging.getLogger("helpdesk.storage")

MOUNTINFO = Path("/proc/self/mountinfo")


def mount_points(mountinfo_text: str) -> set[str]:
    """Mount points from /proc/self/mountinfo (5th field, octal escapes decoded)."""
    points = set()
    for line in mountinfo_text.splitlines():
        fields = line.split()
        if len(fields) >= 5:
            points.add(fields[4].encode().decode("unicode_escape"))
    return points


def is_persistent(db_file: str, mountinfo_text: str) -> bool:
    """True if the database file or one of its parent directories (except /) is mounted."""
    points = mount_points(mountinfo_text) - {"/"}
    # mountinfo only exists on Linux, so paths are POSIX even when tests run on Windows
    if not db_file.startswith("/"):
        db_file = posixpath.join(Path.cwd().as_posix(), db_file)
    path = PurePosixPath(posixpath.normpath(db_file)).parent
    for candidate in (path, *path.parents):
        if candidate.as_posix() in points:
            return True
    return False


def storage_status() -> bool | None:
    """True/False inside Linux containers; None where it cannot be checked (Windows, macOS)."""
    if not MOUNTINFO.exists():
        return None
    return is_persistent(db_path(), MOUNTINFO.read_text())


def warn_if_ephemeral() -> None:
    if os.environ.get("HELPDESK_DB", "").startswith("/data") and storage_status() is False:
        log.warning(
            "Data directory of %s is not a volume: all tickets will be lost when the "
            "container is recreated. Run with -v helpdesk-data:/data (see README).",
            db_path(),
        )
