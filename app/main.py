"""Webserver der Oberfläche:  python -m app.main  ->  http://127.0.0.1:7860

Aufbau:
  app/static/index.html  Gerüst der Seite (wie Gmail)
  app/static/style.css   Aussehen
  app/static/app.js      Verhalten im Browser, ruft die /api/... Adressen unten auf
  app/main.py            diese Datei: liefert die Seite aus und beantwortet die API

Die Seite fragt beim Öffnen und danach jede Minute /api/sync an. Dabei werden
neue Mails geholt und vom Agenten automatisch einsortiert.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import inbox, store
from agent.graph import resume_agent
from agent.tools import call_tool
from mcp_server.google_api import TOKEN_FILE
from schemas import AgentStatus

load_dotenv()

STATIC = Path(__file__).parent / "static"
LIST_FIELDS = ("id", "sender", "subject", "summary", "category", "status", "received_at", "seen")

app = FastAPI(title="LocalMail AI")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _tz() -> ZoneInfo:
    return ZoneInfo(os.getenv("TIMEZONE", "Europe/Zurich"))


# -----------------------------------------------------------------------------
# 1. Die Seite selbst
# -----------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# -----------------------------------------------------------------------------
# 2. Status und Abruf
#    testset=true heisst: Testmails statt Gmail, nichts wird in Google geschrieben.
# -----------------------------------------------------------------------------
@app.get("/api/status")
def status(testset: bool = False):
    """Ist Gmail verbunden, und wie viele ungelesene Mails hat jeder Ordner?"""
    return {
        "gmail_connected": TOKEN_FILE.exists(),
        "unread": store.unread_counts(inbox.source_name(testset)),
    }


@app.post("/api/sync")
def sync(testset: bool = False):
    """Neue Mails holen und vom Agenten einsortieren lassen."""
    try:
        result = inbox.sync(testset)
    except Exception as error:
        raise HTTPException(502, f"Abruf fehlgeschlagen: {error}")
    return {"new": result.new, "failed": result.failed, "busy": result.busy}


# -----------------------------------------------------------------------------
# 3. Mails anzeigen
# -----------------------------------------------------------------------------
@app.get("/api/mails")
def list_mails(testset: bool = False, box: str = store.INBOX, q: str = ""):
    """Mails eines Ordners, optional gefiltert nach Suchbegriff."""
    mails = store.list_emails(inbox.source_name(testset), box, q.strip())
    return [{key: mail[key] for key in LIST_FIELDS} for mail in mails]


def _conflicts(mail: dict) -> list[dict]:
    """Termine im Google Kalender, die sich mit dem Vorschlag überschneiden."""
    event = mail["event"]
    start = datetime.fromisoformat(event["start"]).replace(tzinfo=_tz())
    end = (
        datetime.fromisoformat(event["end"]).replace(tzinfo=_tz())
        if event.get("end")
        else start + timedelta(hours=1)
    )
    try:
        response = call_tool(
            "list_calendar_events", {"time_min": start.isoformat(), "time_max": end.isoformat()}
        )
    except Exception:
        return []  # Kalender nicht erreichbar: Vorschlag trotzdem anzeigen
    return response["events"]


@app.get("/api/mails/{email_id}")
def get_mail(email_id: str):
    """Eine Mail öffnen. Sie gilt danach als gelesen (nur in LocalMail, nicht in Gmail)."""
    mail = store.get_email(email_id)
    if not mail:
        raise HTTPException(404, "Mail nicht gefunden")
    store.mark_seen(email_id)
    waiting = mail["status"] == AgentStatus.AWAITING_CONFIRMATION.value
    conflicts = _conflicts(mail) if waiting and mail["source"] == "gmail" else []
    mail.pop("event_json", None)
    return {**mail, "seen": 1, "conflicts": conflicts}


# -----------------------------------------------------------------------------
# 4. Terminvorschlag bestätigen oder verwerfen
# -----------------------------------------------------------------------------
class Decision(BaseModel):
    approved: bool


@app.post("/api/mails/{email_id}/event")
def decide(email_id: str, decision: Decision):
    mail = store.get_email(email_id)
    if not mail or mail["status"] != AgentStatus.AWAITING_CONFIRMATION.value:
        raise HTTPException(409, "Für diese Mail ist keine Entscheidung offen.")
    try:
        resume_agent(email_id, decision.approved, dry_run=mail["source"] == "test")
    except Exception as error:
        raise HTTPException(502, f"Das hat nicht geklappt: {error}")
    return get_mail(email_id)


# -----------------------------------------------------------------------------
# 5. Google Kalender: Termine der nächsten Tage für die Seitenleiste rechts
# -----------------------------------------------------------------------------
@app.get("/api/calendar")
def calendar(testset: bool = False, days: int = 14):
    if testset:
        # Im Testmodus wird der echte Kalender nicht angefasst.
        events = [
            {**event, "all_day": False, "link": None} for event in store.confirmed_test_events()
        ]
        return {"events": events, "testmode": True}
    now = datetime.now(_tz())
    try:
        response = call_tool(
            "list_calendar_events",
            {"time_min": now.isoformat(), "time_max": (now + timedelta(days=days)).isoformat()},
        )
    except Exception as error:
        raise HTTPException(502, f"Kalender nicht erreichbar: {error}")
    return {"events": response["events"], "testmode": False}


# -----------------------------------------------------------------------------
# 6. Protokoll anzeigen und als Markdown herunterladen
# -----------------------------------------------------------------------------
@app.get("/api/log")
def log():
    return store.list_log()


@app.get("/api/log/export")
def export_log():
    path = store.export_markdown()
    return FileResponse(path, filename="protokoll.md", media_type="text/markdown")


# -----------------------------------------------------------------------------
# 7. Start
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    print(f"LocalMail läuft auf http://127.0.0.1:{port}  (Beenden mit Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
