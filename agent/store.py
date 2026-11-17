"""Dauerhafte Ablage in SQLite (Datei aus SQLITE_PATH, Standard data/localmail.sqlite).

Zwei Tabellen:
  emails        jede abgerufene Mail, nach der Analyse mit Kategorie, Zusammenfassung, Termin
  activity_log  das Protokoll: wer (Agent oder Nutzer) wann was gemacht hat

Status einer Mail in der Tabelle emails:
  pending                abgerufen und sichtbar, aber noch nicht analysiert
  done                   analysiert und eingeordnet
  awaiting_confirmation  Termin gefunden, wartet auf Ja/Nein in der Oberfläche
  failed                 konnte nicht analysiert werden (vom Inhaltsfilter blockiert)
"""

import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(os.getenv("SQLITE_PATH", "data/localmail.sqlite"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Zurich"))


# -----------------------------------------------------------------------------
# 1. Datenbank öffnen und Tabellen anlegen (nur beim ersten Mal)
# -----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,            -- 'gmail' oder 'test'
    thread_id TEXT,
    sender TEXT,
    subject TEXT,
    body TEXT,
    received_at TEXT,
    category TEXT,
    summary TEXT,
    label TEXT,
    status TEXT NOT NULL,            -- siehe Liste oben
    event_json TEXT,                 -- Terminvorschlag als JSON
    event_link TEXT,                 -- Link zum Kalendereintrag
    processed_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0  -- 1 = in der Oberfläche geöffnet
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    actor TEXT NOT NULL,             -- 'agent' oder 'nutzer'
    action TEXT NOT NULL,
    email_id TEXT,
    subject TEXT,
    details TEXT
);
"""


def connect():
    """Öffnet die Datenbank. Zeilen lassen sich wie ein dict lesen: row["subject"]."""
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def run(sql, params=()):
    """Führt einen schreibenden SQL-Befehl aus und speichert ihn (commit)."""
    with closing(connect()) as db, db:
        return db.execute(sql, params).rowcount


def query(sql, params=()):
    """Führt eine Abfrage aus und gibt die Zeilen als Liste von dicts zurück."""
    with closing(connect()) as db:
        return [dict(row) for row in db.execute(sql, params)]


with closing(connect()) as db:
    db.executescript(SCHEMA)
    # Ältere Datenbanken haben die Spalte "seen" noch nicht: nachrüsten.
    if "seen" not in [row["name"] for row in db.execute("PRAGMA table_info(emails)")]:
        db.execute("ALTER TABLE emails ADD COLUMN seen INTEGER NOT NULL DEFAULT 0")
        db.commit()


def now():
    """Aktuelle Zeit als Text, z. B. 2026-11-17T14:05:00+01:00."""
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


# -----------------------------------------------------------------------------
# 2. Protokoll schreiben
# -----------------------------------------------------------------------------
def log(action, email_id=None, subject="", details="", source="gmail", actor="agent"):
    run(
        "INSERT INTO activity_log (timestamp, source, actor, action, email_id, subject, details)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now(), source, actor, action, email_id, subject, details),
    )


# -----------------------------------------------------------------------------
# 3. Mails speichern
#    Ablauf: save_new (pending) -> save_analysis oder save_failed -> save_decision
# -----------------------------------------------------------------------------
def save_new(emails, source):
    """Speichert frisch abgerufene Mails mit Status 'pending', damit sie sofort sichtbar sind.

    Schon bekannte Mails bleiben unverändert (INSERT OR IGNORE).
    Gibt zurück, wie viele Mails neu gespeichert wurden.
    """
    count = 0
    for email in emails:
        count += run(
            "INSERT OR IGNORE INTO emails (id, source, thread_id, sender, subject, body,"
            " received_at, status, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                email["id"],
                source,
                email.get("thread_id", ""),
                email["sender"],
                email["subject"],
                email["body"],
                email.get("received_at"),
                now(),
            ),
        )
    return count


def pending_emails(source, limit):
    """Mails, die noch auf die Analyse warten, neueste zuerst."""
    return query(
        "SELECT id, thread_id, sender, subject, body, received_at FROM emails"
        " WHERE source = ? AND status = 'pending' ORDER BY received_at DESC LIMIT ?",
        (source, limit),
    )


def save_analysis(email_id, values, status):
    """Speichert das Ergebnis des Agenten. values = Zustand (State) des Graphen."""
    analysis = values["analysis"]
    event = analysis.get("event")
    run(
        "UPDATE emails SET category = ?, summary = ?, label = ?, status = ?, event_json = ?,"
        " event_link = ?, processed_at = ? WHERE id = ?",
        (
            analysis["category"],
            analysis["summary"],
            values.get("label_applied"),
            status,
            json.dumps(event) if event else None,
            values.get("event_link"),
            now(),
            email_id,
        ),
    )


def save_failed(email_id, reason):
    """Merkt sich eine Mail, die dauerhaft nicht analysiert werden kann."""
    run(
        "UPDATE emails SET status = 'failed', summary = ?, processed_at = ? WHERE id = ?",
        (reason, now(), email_id),
    )


def save_decision(email_id, status, event_link):
    """Speichert das Ergebnis nach Ja/Nein zu einem Terminvorschlag."""
    run(
        "UPDATE emails SET status = ?, event_link = ?, processed_at = ? WHERE id = ?",
        (status, event_link, now(), email_id),
    )


def mark_seen(email_id):
    run("UPDATE emails SET seen = 1 WHERE id = ?", (email_id,))


# -----------------------------------------------------------------------------
# 4. Mails lesen (für die Oberfläche)
# -----------------------------------------------------------------------------
def known_ids(source):
    """IDs aller Mails, die schon in der Datenbank sind."""
    return {row["id"] for row in query("SELECT id FROM emails WHERE source = ?", (source,))}


def with_event(mail):
    """Wandelt den gespeicherten Termin (Text) wieder in ein dict um."""
    mail["event"] = json.loads(mail["event_json"]) if mail["event_json"] else None
    return mail


def list_emails(source, mailbox, search="", limit=100):
    """Mails eines Ordners. Posteingang = alles ausser Spam, 'failed' = Nicht zugeordnet."""
    if mailbox == "inbox":
        sql, params = "(category IS NULL OR category != 'spam')", []
    elif mailbox == "failed":
        sql, params = "status = 'failed'", []
    else:
        sql, params = "category = ?", [mailbox]

    if search:
        sql += " AND (sender LIKE ? OR subject LIKE ? OR body LIKE ?)"
        params += [f"%{search}%"] * 3

    rows = query(
        f"SELECT * FROM emails WHERE source = ? AND {sql} ORDER BY received_at DESC LIMIT ?",
        [source, *params, limit],
    )
    return [with_event(row) for row in rows]


def get_email(email_id):
    rows = query("SELECT * FROM emails WHERE id = ?", (email_id,))
    return with_event(rows[0]) if rows else None


def unread_counts(source):
    """Anzahl ungelesener Mails pro Ordner (die Zahlen in der Seitenleiste)."""
    rows = query("SELECT category, status FROM emails WHERE source = ? AND seen = 0", (source,))
    counts = Counter(row["category"] for row in rows if row["category"])
    counts["failed"] = sum(row["status"] == "failed" for row in rows)
    counts["inbox"] = sum(row["category"] != "spam" for row in rows)
    return dict(counts)


def confirmed_test_events():
    """Im Testmodus bestätigte Termine (die nicht wirklich im Kalender stehen)."""
    rows = query(
        "SELECT event_json FROM emails WHERE source = 'test'"
        " AND event_json IS NOT NULL AND event_link IS NOT NULL"
    )
    events = [json.loads(row["event_json"]) for row in rows]
    return sorted(events, key=lambda event: event["start"])


# -----------------------------------------------------------------------------
# 5. Protokoll lesen und als Markdown exportieren (für eure Dokumentation)
# -----------------------------------------------------------------------------
def list_log(limit=500):
    return query("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))


def cell(value):
    """Text für eine Markdown-Tabelle: | und Zeilenumbrüche würden die Tabelle zerstören."""
    return (value or "").replace("|", "\\|").replace("\n", " ")


def export_markdown(path="data/protokoll.md"):
    entries = list(reversed(list_log(limit=100_000)))  # älteste zuerst
    categories = query(
        "SELECT source, COALESCE(category, 'nicht zugeordnet') AS category, COUNT(*) AS n"
        " FROM emails GROUP BY 1, 2 ORDER BY 1, 3 DESC"
    )
    actions = Counter(entry["action"] for entry in entries)

    lines = ["# LocalMail AI: Protokoll", "", f"Erstellt am {now()}", "", "## Übersicht", ""]
    lines += ["| Quelle | Kategorie | Anzahl |", "| --- | --- | --- |"]
    lines += [f"| {row['source']} | {row['category']} | {row['n']} |" for row in categories]
    lines += ["", "| Aktion | Anzahl |", "| --- | --- |"]
    lines += [f"| {action} | {n} |" for action, n in actions.most_common()]
    lines += ["", "## Verlauf", ""]
    lines += ["| Zeit | Quelle | Wer | Aktion | Betreff | Details |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [
        f"| {e['timestamp']} | {e['source']} | {e['actor']} | {e['action']} "
        f"| {cell(e['subject'])} | {cell(e['details'])} |"
        for e in entries
    ]

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(target)
