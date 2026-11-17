"""Webserver der Oberfläche:  python -m app.main  ->  http://127.0.0.1:7860

Aufbau:
  app/static/index.html  Gerüst der Seite (wie Gmail)
  app/static/style.css   Aussehen
  app/static/app.js      Verhalten im Browser, ruft die /api/... Adressen unten auf
  app/main.py            diese Datei: liefert die Seite aus und beantwortet die API

Jede Funktion mit @app.get(...) oder @app.post(...) beantwortet eine Adresse.
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

from agent import inbox, llm, store
from agent.graph import resume_agent
from agent.tools import call_tool

load_dotenv()

# Gibt es eine Google-Anmeldung? (Nicht aus mcp_server.server importieren: FastMCP
# würde beim Laden das Logging umstellen und das Terminal mit Meldungen füllen.)
TOKEN_FILE = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
STATIC = Path(__file__).parent / "static"
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Zurich"))
LIST_FIELDS = ["id", "sender", "subject", "summary", "category", "status", "received_at", "seen"]

app = FastAPI(title="LocalMail AI")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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
    # Ohne bereite Engine werden Mails nur abgerufen und angezeigt, nicht analysiert.
    # Sonst würde jede Mail als fehlgeschlagen enden.
    problem = llm.engine_problem()
    try:
        result = inbox.sync(testset, analyze=not problem)
    except Exception as error:
        raise HTTPException(502, f"Abruf fehlgeschlagen: {error}")
    result["skipped"] = problem or None  # Text für die Oberfläche, warum nicht analysiert wurde
    return result


# -----------------------------------------------------------------------------
# 3. KI-Engine: welches Sprachmodell analysiert (lokal oder Cloud)
#    Ein hier gesetzter API-Key bleibt nur im Arbeitsspeicher (llm.engine).
#    Er wird nie an den Browser zurückgeschickt, nicht gespeichert und nicht protokolliert.
# -----------------------------------------------------------------------------
def engine_info():
    """Alles, was der Engine-Dialog in der Oberfläche anzeigt."""
    engine = llm.engine
    problem = llm.engine_problem()
    cloud = engine if engine["provider"] == "cloud" else llm.cloud_from_env()

    local = {}
    for provider, models in llm.local_servers().items():
        local[provider] = {
            "name": llm.NAMES[provider],
            "url": llm.local_url(provider),
            "running": models is not None,
            "models": models or [],
            "default_model": os.getenv(f"{provider.upper()}_MODEL", ""),
        }

    return {
        "provider": engine["provider"],
        "name": llm.NAMES[engine["provider"]],
        "model": engine["model"],
        "is_local": engine["provider"] in llm.LOCAL,
        "ready": not problem,
        "problem": problem,
        "local": local,
        "cloud": {"base_url": cloud["base_url"], "model": cloud["model"], "has_key": bool(cloud["api_key"])},
    }


class EngineChoice(BaseModel):
    """Was der Engine-Dialog schickt."""

    provider: str
    model: str = ""
    base_url: str = ""  # nur für Cloud
    api_key: str = ""   # nur für Cloud; leer = bisherigen Key bzw. Key aus der .env behalten


def engine_from_choice(choice):
    """Macht aus der Auswahl im Dialog eine Engine (dict wie llm.engine)."""
    if choice.provider in llm.LOCAL:
        return {
            "provider": choice.provider,
            "base_url": llm.local_url(choice.provider),
            "model": choice.model.strip(),
            "api_key": "",
        }
    if choice.provider != "cloud":
        raise HTTPException(400, f"Unbekannter Anbieter: {choice.provider}")

    if llm.engine["provider"] == "cloud":
        old_key = llm.engine["api_key"]
    else:
        old_key = llm.cloud_from_env()["api_key"]
    return {
        "provider": "cloud",
        "base_url": choice.base_url.strip().rstrip("/"),
        "model": choice.model.strip(),
        "api_key": choice.api_key.strip() or old_key,
    }


@app.get("/api/engine")
def get_engine():
    """Gewählte Engine, ob sie bereit ist, und welche lokalen Server laufen."""
    return engine_info()


@app.post("/api/engine")
def set_engine(choice: EngineChoice):
    """Engine umstellen. Gilt sofort für alle folgenden Analysen, bis zum Neustart."""
    llm.engine = engine_from_choice(choice)
    details = f"{llm.NAMES[llm.engine['provider']]}, {llm.engine['model']}"
    store.log("engine_gewechselt", details=details, source="app", actor="nutzer")
    return engine_info()


@app.post("/api/engine/test")
def test_engine(choice: EngineChoice):
    """Verbindungstest: fragt nur die Modellliste ab, ruft kein Modell auf."""
    engine = engine_from_choice(choice)
    if not engine["base_url"]:
        return {"ok": False, "message": "Basis-URL fehlt."}
    if engine["provider"] == "cloud" and not engine["api_key"]:
        return {"ok": False, "message": "API-Key fehlt."}
    try:
        models = llm.list_models(engine["base_url"], engine["api_key"], timeout=8)
    except llm.ConnectionProblem as problem:
        return {"ok": False, "message": str(problem)}
    if engine["model"] in models:
        found = "Modell gefunden."
    else:
        found = "Modell steht nicht in der Liste des Anbieters."
    return {"ok": True, "message": f"Verbindung ok, {len(models)} Modelle verfügbar. {found}"}


# -----------------------------------------------------------------------------
# 4. Mails anzeigen
# -----------------------------------------------------------------------------
@app.get("/api/mails")
def list_mails(testset: bool = False, box: str = "inbox", q: str = ""):
    """Mails eines Ordners, optional gefiltert nach Suchbegriff."""
    mails = store.list_emails(inbox.source_name(testset), box, q.strip())
    return [{key: mail[key] for key in LIST_FIELDS} for mail in mails]


def find_conflicts(event):
    """Termine im Google Kalender, die sich mit dem Vorschlag überschneiden."""
    start = datetime.fromisoformat(event["start"]).replace(tzinfo=TIMEZONE)
    if event.get("end"):
        end = datetime.fromisoformat(event["end"]).replace(tzinfo=TIMEZONE)
    else:
        end = start + timedelta(hours=1)
    try:
        response = call_tool("list_calendar_events", {"time_min": start.isoformat(), "time_max": end.isoformat()})
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

    conflicts = []
    if mail["status"] == "awaiting_confirmation" and mail["source"] == "gmail":
        conflicts = find_conflicts(mail["event"])
    mail.pop("event_json")  # der Browser bekommt den Termin schon als "event"
    return {**mail, "seen": 1, "conflicts": conflicts}


# -----------------------------------------------------------------------------
# 5. Terminvorschlag bestätigen oder verwerfen
# -----------------------------------------------------------------------------
class Decision(BaseModel):
    approved: bool


@app.post("/api/mails/{email_id}/event")
def decide(email_id: str, decision: Decision):
    mail = store.get_email(email_id)
    if not mail or mail["status"] != "awaiting_confirmation":
        raise HTTPException(409, "Für diese Mail ist keine Entscheidung offen.")
    try:
        resume_agent(email_id, decision.approved, dry_run=mail["source"] == "test")
    except Exception as error:
        raise HTTPException(502, f"Das hat nicht geklappt: {error}")
    return get_mail(email_id)


# -----------------------------------------------------------------------------
# 6. Google Kalender: Termine der nächsten Tage für die Seitenleiste rechts
# -----------------------------------------------------------------------------
@app.get("/api/calendar")
def calendar(testset: bool = False, days: int = 14):
    if testset:
        # Im Testmodus wird der echte Kalender nicht angefasst.
        events = [{**event, "all_day": False, "link": None} for event in store.confirmed_test_events()]
        return {"events": events, "testmode": True}

    now = datetime.now(TIMEZONE)
    try:
        response = call_tool(
            "list_calendar_events",
            {"time_min": now.isoformat(), "time_max": (now + timedelta(days=days)).isoformat()},
        )
    except Exception as error:
        raise HTTPException(502, f"Kalender nicht erreichbar: {error}")
    return {"events": response["events"], "testmode": False}


# -----------------------------------------------------------------------------
# 7. Protokoll anzeigen und als Markdown herunterladen
# -----------------------------------------------------------------------------
@app.get("/api/log")
def log():
    return store.list_log()


@app.get("/api/log/export")
def export_log():
    path = store.export_markdown()
    return FileResponse(path, filename="protokoll.md", media_type="text/markdown")


# -----------------------------------------------------------------------------
# 8. Start
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    print(f"LocalMail läuft auf http://127.0.0.1:{port}  (Beenden mit Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
