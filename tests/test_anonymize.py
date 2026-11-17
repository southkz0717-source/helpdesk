import sqlite3

import pytest

from scripts.anonymize import anonymize, mask_text, pseudonym

KEY = b"test-key"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Жазыңыз: aigerim.n@mail.kz", "Жазыңыз: [email]"),
        ("Тел. +7 701 123 45 67", "Тел. [phone]"),
        ("звоните 8(777)123-45-67", "звоните [phone]"),
        ("ЖСН 990101300123", "ЖСН [iin]"),
        ("карта 4400 4301 2345 6789", "карта [card]"),
        ("Принтер 305 аудиторияда", "Принтер 305 аудиторияда"),  # no personal data
    ],
)
def test_mask_text(text, expected):
    assert mask_text(text) == expected


def test_pseudonym_is_stable_and_hides_name():
    assert pseudonym("Айгерім", KEY) == pseudonym("  айгерім ", KEY)
    assert pseudonym("Айгерім", KEY) != pseudonym("Ерлан", KEY)
    assert "Айгерім" not in pseudonym("Айгерім", KEY)
    assert pseudonym("Айгерім", KEY) != pseudonym("Айгерім", b"other-key")


def test_anonymize_copy(client, tmp_path):
    client.post(
        "/api/tickets",
        json={"title": "Почта не работает", "requester": "Айгерім Нұрланқызы", "priority": "P2",
              "description": "Пишите на aigerim.n@mail.kz или +7 701 123 45 67"},
    )  # fmt: skip
    client.post(
        "/api/tickets",
        json={"title": "VPN", "requester": "Айгерім Нұрланқызы", "priority": "P3"},
    )
    src, dst = tmp_path / "test.db", tmp_path / "stand.db"

    assert anonymize(src, dst, KEY) == 2

    rows = (
        sqlite3.connect(dst)
        .execute("SELECT requester, description, priority, status FROM tickets ORDER BY id")
        .fetchall()
    )
    dump = repr(rows) + dst.read_bytes().decode("utf-8", errors="ignore")
    assert "Айгерім" not in dump and "aigerim" not in dump and "701" not in dump
    assert rows[0][0] == rows[1][0]  # same person -> same pseudonym
    assert rows[0][1] == "Пишите на [email] или [phone]"
    assert [r[2] for r in rows] == ["P2", "P3"]  # priorities kept
    # the source is untouched
    assert sqlite3.connect(src).execute("SELECT requester FROM tickets").fetchone()[0] == (
        "Айгерім Нұрланқызы"
    )


def test_refuses_to_overwrite(tmp_path):
    (tmp_path / "a.db").write_bytes(b"")
    (tmp_path / "b.db").write_bytes(b"x")
    with pytest.raises(SystemExit):
        anonymize(tmp_path / "a.db", tmp_path / "b.db", KEY)
