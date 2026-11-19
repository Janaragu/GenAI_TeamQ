"""Eigener MCP-Server mit Werkzeugen für Gmail und Google Kalender.

Wie der eigene MCP-Server im Notebook 06: Jede Funktion mit @mcp.tool() ist ein
Werkzeug. Ihr Docstring ist die Beschreibung, die der Client zu sehen bekommt.

Start (macht agent/tools.py automatisch):  python -m mcp_server.server
Die Anmeldung bei Google steht in token.json (einmalig: python -m mcp_server.auth).
"""

import base64
import os
import socket
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

load_dotenv()

# In manchen Netzen ist Google über IPv6 nicht erreichbar. Python versucht IPv6
# zuerst, und der Gmail-Abruf bricht mit "timed out" ab, statt auf IPv4 auszuweichen.
# GOOGLE_FORCE_IPV4=1 in .env: nur IPv4-Adressen verwenden (wenn es welche gibt).
if os.getenv("GOOGLE_FORCE_IPV4", "").lower() in ("1", "true", "yes"):
    _getaddrinfo = socket.getaddrinfo

    def _ipv4_only(*args, **kwargs):
        results = _getaddrinfo(*args, **kwargs)
        return [r for r in results if r[0] == socket.AF_INET] or results

    socket.getaddrinfo = _ipv4_only

# gmail.modify = Mails lesen, Labels setzen und Antworten senden (nicht löschen),
# calendar.events = Termine
DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify,"
    "https://www.googleapis.com/auth/calendar.events"
)
SCOPES = os.getenv("GOOGLE_SCOPES", DEFAULT_SCOPES).split(",")
TOKEN_FILE = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
CREDENTIALS_FILE = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Zurich")

mcp = FastMCP("localmail")


# -----------------------------------------------------------------------------
# 1. Anmeldung bei Google: Token laden und bei Bedarf automatisch erneuern
# -----------------------------------------------------------------------------
def credentials():
    if not TOKEN_FILE.exists():
        raise RuntimeError(f"{TOKEN_FILE} fehlt. Zuerst anmelden: python -m mcp_server.auth")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise RuntimeError("Google-Token ungültig. Neu anmelden: python -m mcp_server.auth")
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def gmail():
    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)


def calendar():
    return build("calendar", "v3", credentials=credentials(), cache_discovery=False)


# -----------------------------------------------------------------------------
# 2. Mailtext auslesen
#    Gmail liefert eine Mail in verschachtelten Teilen (MIME), Base64-kodiert.
#    Bevorzugt wird reiner Text, sonst HTML ohne Tags.
# -----------------------------------------------------------------------------
def find_part(payload, mime_type):
    """Sucht in allen Teilen der Mail den ersten mit diesem Typ und gibt ihn als Text zurück."""
    data = payload.get("body", {}).get("data")
    if payload.get("mimeType") == mime_type and data:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        found = find_part(part, mime_type)
        if found:
            return found
    return None


def mail_body(payload):
    text = find_part(payload, "text/plain")
    if text:
        return text
    html = find_part(payload, "text/html")
    if html:
        return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return ""


# -----------------------------------------------------------------------------
# 3. Gmail-Werkzeuge
# -----------------------------------------------------------------------------
@mcp.tool()
def list_email_ids(query: str = "in:inbox", max_results: int = 25) -> dict:
    """Liefert die IDs der neuesten Mails zu einer Gmail-Suchanfrage."""
    listing = gmail().users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return {"ids": [ref["id"] for ref in listing.get("messages", [])]}


@mcp.tool()
def get_emails(ids: list[str]) -> dict:
    """Liefert Absender, Betreff, Text und Datum zu den angegebenen Mail-IDs."""
    service = gmail()
    emails = []
    for message_id in ids:
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
        # internalDate = Empfangszeit in Millisekunden seit 1970 (UTC)
        received = datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=timezone.utc)
        emails.append({
            "id": message["id"],
            "thread_id": message["threadId"],
            "sender": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "body": mail_body(message["payload"]),
            "received_at": received.isoformat(),
        })
    return {"emails": emails}


@mcp.tool()
def apply_label(message_id: str, label_name: str) -> dict:
    """Versieht eine Mail mit einem Label und legt es bei Bedarf an."""
    service = gmail()
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label_id = next((label["id"] for label in labels if label["name"] == label_name), None)
    if label_id is None:  # Label gibt es noch nicht: anlegen
        label_id = service.users().labels().create(userId="me", body={"name": label_name}).execute()["id"]
    service.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": [label_id]}).execute()
    return {"ok": True}


@mcp.tool()
def send_reply(message_id: str, body: str) -> dict:
    """Beantwortet eine Mail. Die Antwort landet im selben Verlauf (Thread) wie das Original."""
    service = gmail()
    # Vom Original brauchen wir nur ein paar Kopfzeilen, nicht den ganzen Text.
    original = service.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"],
    ).execute()
    headers = {h["name"].lower(): h["value"] for h in original["payload"].get("headers", [])}

    subject = headers.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    reply = MIMEText(body, "plain", "utf-8")
    reply["To"] = headers.get("reply-to") or headers.get("from", "")  # Reply-To hat Vorrang
    reply["Subject"] = subject
    # Diese zwei Kopfzeilen sagen dem Mailprogramm des Empfängers, worauf geantwortet wird.
    if headers.get("message-id"):
        reply["In-Reply-To"] = headers["message-id"]
        reply["References"] = f"{headers.get('references', '')} {headers['message-id']}".strip()

    # Gmail erwartet die ganze Mail Base64-kodiert. Absender ist das angemeldete Konto.
    raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
    sent = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": original["threadId"]}
    ).execute()
    return {"id": sent["id"]}


# -----------------------------------------------------------------------------
# 4. Kalender-Werkzeuge
# -----------------------------------------------------------------------------
@mcp.tool()
def list_calendar_events(time_min: str, time_max: str, max_results: int = 50) -> dict:
    """Liefert die Termine im Zeitraum (ISO-8601 mit Zeitzone)."""
    response = calendar().events().list(
        calendarId=CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,  # Serientermine einzeln auflisten
        orderBy="startTime",
        maxResults=max_results,
    ).execute()

    events = []
    for item in response.get("items", []):
        start, end = item.get("start", {}), item.get("end", {})
        events.append({
            "title": item.get("summary", "(ohne Titel)"),
            # Ganztägige Termine haben nur "date", alle anderen "dateTime".
            "start": start.get("dateTime", start.get("date")),
            "end": end.get("dateTime", end.get("date")),
            "all_day": "date" in start,
            "location": item.get("location"),
            "link": item.get("htmlLink"),
        })
    return {"events": events}


@mcp.tool()
def create_calendar_event(
    title: str, start: str, end: str, location: str | None = None, description: str | None = None
) -> dict:
    """Trägt einen Termin ein. start und end sind ISO-8601 in Ortszeit."""
    body = {
        "summary": title,
        "start": {"dateTime": start, "timeZone": TIMEZONE},
        "end": {"dateTime": end, "timeZone": TIMEZONE},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    event = calendar().events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return {"link": event.get("htmlLink", "")}


# -----------------------------------------------------------------------------
# Start: Der Server spricht über stdin/stdout (stdio) mit dem Client.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
