"""MCP-Server mit Gmail- und Kalender-Werkzeugen (stdio): python -m mcp_server.server"""

from mcp.server.fastmcp import FastMCP

from mcp_server import google_api

mcp = FastMCP("localmail")


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


@mcp.tool()
def create_calendar_event(
    title: str, start: str, end: str, location: str | None = None, description: str | None = None
) -> dict:
    """Trägt einen Termin ein. start und end sind ISO-8601 in Ortszeit."""
    return {"link": google_api.create_event(title, start, end, location, description)}


if __name__ == "__main__":
    mcp.run()
