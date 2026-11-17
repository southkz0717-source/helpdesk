"""Make an anonymized copy of a production database for the test stand.

Lecture 11: a copy of the production base on a test stand is the most common
cause of personal data leaks. Removing surnames is not enough, values must be
REPLACED, and the data must stay realistic (volumes, priorities, statuses, dates).

What happens to each column:
    requester    -> pseudonym "Пайдаланушы-0042". The same person always gets the
                    same pseudonym (keyed hash), so "how many tickets per user" is preserved
    description  -> e-mails, phone numbers, IIN (12 digits) and card numbers are masked
    title        -> same masking as description
    priority, status, dates -> kept: they carry no personal data and are needed for
                    SLA and load testing

Usage:
    python scripts/anonymize.py prod.db test-stand.db
The secret for pseudonyms is taken from ANONYMIZE_KEY (keep it out of the repo);
without it a random key is used and pseudonyms differ between runs.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from pathlib import Path

PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (
        re.compile(r"(?<!\d)(?:\+?7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"),
        "[phone]",
    ),
    (re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"), "[card]"),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[iin]"),
]


def mask_text(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def pseudonym(name: str, key: bytes) -> str:
    digest = hmac.new(key, name.strip().casefold().encode(), hashlib.sha256).hexdigest()
    return f"Пайдаланушы-{int(digest[:8], 16) % 10000:04d}"


def anonymize(src: Path, dst: Path, key: bytes) -> int:
    if dst.exists():
        raise SystemExit(f"{dst} already exists, refusing to overwrite")
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)  # consistent copy even while the service is writing
    conn = sqlite3.connect(dst)
    rows = conn.execute("SELECT id, title, description, requester FROM tickets").fetchall()
    for ticket_id, title, description, requester in rows:
        conn.execute(
            "UPDATE tickets SET title = ?, description = ?, requester = ? WHERE id = ?",
            (mask_text(title), mask_text(description or ""), pseudonym(requester, key), ticket_id),
        )
    conn.commit()
    conn.execute("VACUUM")  # drop the old values from free pages of the file
    conn.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Anonymized copy of a helpdesk database")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    key = os.environ.get("ANONYMIZE_KEY", "").encode() or secrets.token_bytes(32)
    count = anonymize(args.source, args.target, key)
    print(f"{count} tickets anonymized -> {args.target}")


if __name__ == "__main__":
    main()
