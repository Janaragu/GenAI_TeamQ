"""Zugriff auf Gmail und Google Calendar."""

import base64
import os
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify,"
    "https://www.googleapis.com/auth/calendar.events"
)
SCOPES = os.getenv("GOOGLE_SCOPES", DEFAULT_SCOPES).split(",")
TOKEN_FILE = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
CREDENTIALS_FILE = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"))


def _credentials() -> Credentials:
    if not TOKEN_FILE.exists():
        raise RuntimeError(f"{TOKEN_FILE} fehlt. Zuerst anmelden: python -m mcp_server.auth")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise RuntimeError("Google-Token ungültig. Neu anmelden: python -m mcp_server.auth")
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _gmail():
    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


def _calendar():
    return build("calendar", "v3", credentials=_credentials(), cache_discovery=False)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")


def _find_part(payload: dict, mime_type: str) -> str | None:
    if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []):
        found = _find_part(part, mime_type)
        if found:
            return found
    return None


def _body(payload: dict) -> str:
    text = _find_part(payload, "text/plain")
    if text:
        return text
    html = _find_part(payload, "text/html")
    if html:
        return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return ""


def list_ids(query: str, max_results: int) -> list[str]:
    listing = (
        _gmail().users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    )
    return [ref["id"] for ref in listing.get("messages", [])]


def get_messages(ids: list[str]) -> list[dict]:
    service = _gmail()
    emails = []
    for message_id in ids:
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
        received = datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=timezone.utc)
        emails.append(
            {
                "id": message["id"],
                "thread_id": message["threadId"],
                "sender": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "body": _body(message["payload"]),
                "received_at": received.isoformat(),
            }
        )
    return emails


def _label_id(service, name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"] == name:
            return label["id"]
    return service.users().labels().create(userId="me", body={"name": name}).execute()["id"]


def apply_label(message_id: str, label_name: str) -> None:
    service = _gmail()
    body = {"addLabelIds": [_label_id(service, label_name)]}
    service.users().messages().modify(userId="me", id=message_id, body=body).execute()


def create_event(
    title: str, start: str, end: str, location: str | None, description: str | None
) -> str:
    tz = os.getenv("TIMEZONE", "Europe/Zurich")
    body = {
        "summary": title,
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    event = _calendar().events().insert(calendarId=calendar_id, body=body).execute()
    return event.get("htmlLink", "")
