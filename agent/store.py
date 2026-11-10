"""Dauerhafte Ablage in SQLite: verarbeitete Mails und Protokoll aller Aktionen."""

import json
import os
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from schemas import AgentResult, Email

load_dotenv()

STATUS_FAILED = "failed"
INBOX = "inbox"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    thread_id TEXT,
    sender TEXT,
    subject TEXT,
    body TEXT,
    received_at TEXT,
    category TEXT,
    summary TEXT,
    label TEXT,
    status TEXT NOT NULL,
    event_json TEXT,
    event_link TEXT,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    email_id TEXT,
    subject TEXT,
    details TEXT
);
"""


def _now() -> str:
    tz = ZoneInfo(os.getenv("TIMEZONE", "Europe/Zurich"))
    return datetime.now(tz).isoformat(timespec="seconds")


@contextmanager
def _db():
    path = Path(os.getenv("SQLITE_PATH", "data/localmail.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(_SCHEMA)
        with connection:
            yield connection
    finally:
        connection.close()


def log(
    action: str,
    email_id: str | None = None,
    subject: str = "",
    details: str = "",
    source: str = "gmail",
    actor: str = "agent",
) -> None:
    with _db() as db:
        db.execute(
            "INSERT INTO activity_log (timestamp, source, actor, action, email_id, subject, details)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_now(), source, actor, action, email_id, subject, details),
        )


def save_result(email: Email, result: AgentResult, source: str) -> None:
    event = result.analysis.event
    with _db() as db:
        db.execute(
            "INSERT OR REPLACE INTO emails (id, source, thread_id, sender, subject, body, received_at,"
            " category, summary, label, status, event_json, event_link, processed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email.id,
                source,
                email.thread_id,
                email.sender,
                email.subject,
                email.body,
                email.received_at.isoformat() if email.received_at else None,
                result.analysis.category.value,
                result.analysis.summary,
                result.label_applied,
                result.status.value,
                event.model_dump_json() if event else None,
                result.event_link,
                _now(),
            ),
        )


def save_failed(email: Email, source: str, reason: str) -> None:
    """Merkt sich eine Mail, die dauerhaft nicht analysiert werden kann."""
    with _db() as db:
        db.execute(
            "INSERT OR REPLACE INTO emails (id, source, thread_id, sender, subject, body, received_at,"
            " summary, status, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email.id,
                source,
                email.thread_id,
                email.sender,
                email.subject,
                email.body,
                email.received_at.isoformat() if email.received_at else None,
                reason,
                STATUS_FAILED,
                _now(),
            ),
        )


def update_after_decision(result: AgentResult) -> None:
    with _db() as db:
        db.execute(
            "UPDATE emails SET status = ?, event_link = ?, processed_at = ? WHERE id = ?",
            (result.status.value, result.event_link, _now(), result.email_id),
        )


def known_ids(source: str) -> set[str]:
    with _db() as db:
        rows = db.execute("SELECT id FROM emails WHERE source = ?", (source,)).fetchall()
    return {row["id"] for row in rows}


def _mailbox_filter(mailbox: str) -> tuple[str, list[str]]:
    if mailbox == INBOX:
        return "(category IS NULL OR category != 'spam')", []
    if mailbox == STATUS_FAILED:
        return "status = ?", [STATUS_FAILED]
    return "category = ?", [mailbox]


def _to_dict(row: sqlite3.Row) -> dict:
    mail = dict(row)
    mail["event"] = json.loads(mail["event_json"]) if mail["event_json"] else None
    return mail


def list_emails(source: str, mailbox: str, search: str = "", limit: int = 100) -> list[dict]:
    clause, params = _mailbox_filter(mailbox)
    sql = f"SELECT * FROM emails WHERE source = ? AND {clause}"
    args = [source, *params]
    if search:
        sql += " AND (sender LIKE ? OR subject LIKE ? OR body LIKE ?)"
        args += [f"%{search}%"] * 3
    sql += " ORDER BY received_at DESC LIMIT ?"
    with _db() as db:
        return [_to_dict(row) for row in db.execute(sql, [*args, limit]).fetchall()]


def get_email(email_id: str) -> dict | None:
    with _db() as db:
        row = db.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    return _to_dict(row) if row else None


def mailbox_counts(source: str) -> dict[str, int]:
    with _db() as db:
        rows = db.execute(
            "SELECT category, status FROM emails WHERE source = ?", (source,)
        ).fetchall()
    counts = Counter(row["category"] for row in rows if row["category"])
    counts[STATUS_FAILED] = sum(row["status"] == STATUS_FAILED for row in rows)
    counts[INBOX] = sum(row["category"] != "spam" for row in rows)
    return dict(counts)


def list_log(limit: int = 500) -> list[dict]:
    with _db() as db:
        rows = db.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def _cell(value: str | None) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")


def export_markdown(path: str = "data/protokoll.md") -> str:
    """Schreibt das gesamte Protokoll als Markdown-Datei für die Dokumentation."""
    entries = list(reversed(list_log(limit=100_000)))
    with _db() as db:
        categories = db.execute(
            "SELECT source, COALESCE(category, 'nicht zugeordnet') AS category, COUNT(*) AS n"
            " FROM emails GROUP BY 1, 2 ORDER BY 1, 3 DESC"
        ).fetchall()

    lines = ["# LocalMail AI: Protokoll", "", f"Erstellt am {_now()}", "", "## Übersicht", ""]
    lines += ["| Quelle | Kategorie | Anzahl |", "| --- | --- | --- |"]
    lines += [f"| {row['source']} | {row['category']} | {row['n']} |" for row in categories]
    lines += ["", "| Aktion | Anzahl |", "| --- | --- |"]
    lines += [f"| {a} | {n} |" for a, n in Counter(e["action"] for e in entries).most_common()]
    lines += ["", "## Verlauf", ""]
    lines += ["| Zeit | Quelle | Wer | Aktion | Betreff | Details |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [
        f"| {e['timestamp']} | {e['source']} | {e['actor']} | {e['action']} "
        f"| {_cell(e['subject'])} | {_cell(e['details'])} |"
        for e in entries
    ]

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(target)
