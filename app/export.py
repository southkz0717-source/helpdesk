"""CSV export of the ticket list, made to open correctly in Excel.

- UTF-8 with BOM, otherwise Excel shows Kazakh and Russian letters as garbage;
- ';' as the delimiter: Excel in kk/ru locales expects it, ',' puts everything in one column;
- formula injection guard (OWASP "CSV injection"): a cell starting with = + - @ or a
  tab/CR is prefixed with ', so a ticket titled "=HYPERLINK(...)" stays plain text.
"""

import csv
import io

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def tickets_csv(tickets: list[dict], t: dict, fmt_time) -> str:
    """`t` is the interface strings of the chosen language, `fmt_time` formats a datetime."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["#", t["title"], t["requester"], t["priority"], t["status"], t["assignee"],
                     t["created"], t["response_due"], t["resolve_due"], t["resolved_at"],
                     t["breached"]])  # fmt: skip
    for tk in tickets:
        breached = tk.get("response_breached") or tk.get("resolve_breached")
        writer.writerow([
            tk["id"], safe_cell(tk["title"]), safe_cell(tk["requester"]), tk["priority"],
            t[tk["status"]], safe_cell(tk.get("assignee") or ""),
            fmt_time(tk["created_at"]), fmt_time(tk["response_due"]),
            fmt_time(tk["resolve_due"]), fmt_time(tk["resolved_at"]),
            t["yes"] if breached else "",
        ])  # fmt: skip
    return "﻿" + out.getvalue()
