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
from pydantic import BaseModel, Field

from agent import chat, inbox, llm, reply, store
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
# 6. Antworten: KI-Entwurf holen, danach selbst senden
#    Der Entwurf wird nur angezeigt. Gesendet wird erst, wenn der Nutzer "Senden" drückt.
# -----------------------------------------------------------------------------
class DraftRequest(BaseModel):
    instruction: str  # z. B. "Termin annehmen" oder "Lehne freundlich ab"


class SendRequest(BaseModel):
    body: str  # der fertige Antworttext aus dem Antwortfeld


def mail_or_404(email_id):
    mail = store.get_email(email_id)
    if not mail:
        raise HTTPException(404, "Mail nicht gefunden")
    return mail


@app.post("/api/mails/{email_id}/reply/draft")
def draft_reply(email_id: str, request: DraftRequest):
    """Lässt das LLM einen Antworttext schreiben. Sendet nichts."""
    mail = mail_or_404(email_id)
    problem = llm.engine_problem()
    if problem:
        raise HTTPException(409, f"KI-Engine nicht bereit: {problem}")
    try:
        return {"body": reply.draft_reply(mail, request.instruction.strip())}
    except Exception as error:
        raise HTTPException(502, f"Entwurf fehlgeschlagen: {error}")


@app.post("/api/mails/{email_id}/reply/send")
def send_reply(email_id: str, request: SendRequest):
    """Sendet die Antwort über Gmail (im Testmodus nur ins Protokoll)."""
    mail = mail_or_404(email_id)
    if not request.body.strip():
        raise HTTPException(400, "Die Antwort ist leer.")
    try:
        return reply.send_reply(mail, request.body)
    except Exception as error:
        raise HTTPException(502, f"Senden fehlgeschlagen: {error}")


# -----------------------------------------------------------------------------
# 7. Chatfenster: Fragen zu den eigenen Mails (Guardrails in agent/chat.py)
# -----------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str   # "user" oder "assistant"
    text: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    # max_length ist eine Guardrail: zu lange Fragen lehnt FastAPI direkt ab (Fehler 422).
    question: str = Field(min_length=1, max_length=chat.MAX_QUESTION_CHARS)
    history: list[ChatMessage] = []


@app.post("/api/chat")
def ask_chat(request: ChatRequest, testset: bool = False):
    """Beantwortet eine Frage zu den Mails. Kann einen Antwort-Entwurf mitliefern, sendet aber nie."""
    problem = llm.engine_problem()
    if problem:
        raise HTTPException(409, f"KI-Engine nicht bereit: {problem}")
    history = [message.model_dump() for message in request.history]
    try:
        return chat.ask(request.question.strip(), history, inbox.source_name(testset))
    except Exception as error:
        raise HTTPException(502, f"Chat fehlgeschlagen: {error}")


# -----------------------------------------------------------------------------
# 8. Google Kalender: Termine der nächsten Tage für die Seitenleiste rechts
# -----------------------------------------------------------------------------
@app.get("/api/calendar")
def calendar(testset: bool = False, year: int = 0, month: int = 0):
    """Termine eines Monats: aus Google Kalender und aus Mails mit Label Termin.

    Ohne year/month: der aktuelle Monat. Jeder Termin hat ein Feld state:
      google      steht nur im Google Kalender
      vorschlag / bestaetigt / verworfen   kommt aus einer Mail (siehe store.termin_mail_events)
    """
    today = datetime.now(TIMEZONE)
    year = year or today.year
    month = month or today.month
    mail_events = store.termin_mail_events(inbox.source_name(testset), f"{year}-{month:02d}")

    def by_start(event):
        return event["start"]

    if testset:
        # Im Testmodus wird der echte Kalender nicht angefasst, nur die Testmails zählen.
        return {"events": sorted(mail_events, key=by_start), "testmode": True, "error": None}

    # Google Kalender für den ganzen Monat lesen. Klappt das nicht, trotzdem die Mail-Termine zeigen.
    first_day = datetime(year, month, 1, tzinfo=TIMEZONE)
    next_month = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=TIMEZONE)
    error = None
    try:
        google = call_tool("list_calendar_events", {
            "time_min": first_day.isoformat(),
            "time_max": next_month.isoformat(),
            "max_results": 250,
        })["events"]
    except Exception as problem:
        google, error = [], f"Google Kalender nicht erreichbar: {problem}"

    # Bestätigte Termine aus Mails stehen schon im Google Kalender (gleicher Link).
    # Dort nur vermerken, aus welcher Mail sie stammen, statt sie doppelt zu zeigen.
    mail_by_link = {event["link"]: event for event in mail_events if event["link"]}
    events = []
    for event in google:
        from_mail = mail_by_link.pop(event.get("link"), None)
        if from_mail:
            events.append({**event, "mail_id": from_mail["mail_id"], "state": "bestaetigt"})
        else:
            events.append({**event, "mail_id": None, "state": "google"})
    shown_links = {event.get("link") for event in google}
    events += [event for event in mail_events if not event["link"] or event["link"] not in shown_links]
    return {"events": sorted(events, key=by_start), "testmode": False, "error": error}


# -----------------------------------------------------------------------------
# 9. Alles zurücksetzen (z. B. vor einer Demo)
# -----------------------------------------------------------------------------
@app.post("/api/reset")
def reset():
    """Löscht Mails, Protokoll und Agenten-Stand in der lokalen Datenbank. Gmail bleibt, wie es ist."""
    # Nicht mitten in einen Abruf hinein löschen: dieselbe Sperre wie in agent/inbox.py.
    if not inbox.lock.acquire(blocking=False):
        raise HTTPException(409, "Gerade läuft ein Abruf. Bitte kurz warten und nochmals versuchen.")
    try:
        store.reset_all()
        store.log("zurückgesetzt", details="Alle Mails und das Protokoll gelöscht", source="app", actor="nutzer")
    finally:
        inbox.lock.release()
    return {"ok": True}


# -----------------------------------------------------------------------------
# 10. Protokoll anzeigen und als Markdown herunterladen
# -----------------------------------------------------------------------------
@app.get("/api/log")
def log():
    return store.list_log()


@app.get("/api/log/export")
def export_log():
    path = store.export_markdown()
    return FileResponse(path, filename="protokoll.md", media_type="text/markdown")


# -----------------------------------------------------------------------------
# 11. Start
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    print(f"LocalMail läuft auf http://127.0.0.1:{port}  (Beenden mit Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
