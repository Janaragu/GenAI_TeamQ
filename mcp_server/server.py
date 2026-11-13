"""MCP-Server: stellt Gmail und Google Kalender als Werkzeuge (Tools) bereit.

Start (macht agent/tools.py automatisch):  python -m mcp_server.server
Jede Funktion mit @mcp.tool() ist ein Werkzeug. Der Docstring ist die
Beschreibung, die ein Client (oder ein LLM) zu sehen bekommt.
"""

from mcp.server.fastmcp import FastMCP

from mcp_server import google_api

mcp = FastMCP("localmail")


# -----------------------------------------------------------------------------
# Gmail-Werkzeuge
# -----------------------------------------------------------------------------
@mcp.tool()
def list_email_ids(query: str = "in:inbox", max_results: int = 25) -> dict:
    """Liefert die IDs der neuesten Mails zu einer Gmail-Suchanfrage."""
    return {"ids": google_api.list_ids(query, max_results)}


@mcp.tool()
def get_emails(ids: list[str]) -> dict:
    """Liefert Absender, Betreff, Text und Datum zu den angegebenen Mail-IDs."""
    return {"emails": google_api.get_messages(ids)}


@mcp.tool()
def apply_label(message_id: str, label_name: str) -> dict:
    """Versieht eine Mail mit einem Label und legt es bei Bedarf an."""
    google_api.apply_label(message_id, label_name)
    return {"ok": True}


# -----------------------------------------------------------------------------
# Kalender-Werkzeuge
# -----------------------------------------------------------------------------
@mcp.tool()
def list_calendar_events(time_min: str, time_max: str, max_results: int = 50) -> dict:
    """Liefert die Termine im Zeitraum (ISO-8601 mit Zeitzone)."""
    return {"events": google_api.list_events(time_min, time_max, max_results)}


@mcp.tool()
def create_calendar_event(
    title: str, start: str, end: str, location: str | None = None, description: str | None = None
) -> dict:
    """Trägt einen Termin ein. start und end sind ISO-8601 in Ortszeit."""
    return {"link": google_api.create_event(title, start, end, location, description)}


# -----------------------------------------------------------------------------
# Start: Der Server spricht über stdin/stdout (stdio) mit dem Client.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
