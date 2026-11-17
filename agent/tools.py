"""Verbindung zum eigenen MCP-Server (mcp_server/server.py).

Wie im Notebook 06: MultiServerMCPClient startet den Server als eigenen Prozess
und spricht über stdin/stdout mit ihm (transport "stdio"). Der Agent greift nie
direkt auf Gmail oder den Kalender zu, sondern immer über diese Werkzeuge.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

ROOT = Path(__file__).resolve().parent.parent  # Hauptordner des Projekts

client = MultiServerMCPClient({
    "localmail": {
        "command": sys.executable,             # derselbe Python wie diese App
        "args": ["-m", "mcp_server.server"],
        "transport": "stdio",                  # Kommunikation über die Standardeingabe
        "cwd": str(ROOT),                      # damit der Server .env und token.json findet
        "env": dict(os.environ),               # gleiche Umgebungsvariablen wie die App
    }
})


async def call_tool_async(name, arguments):
    """Startet den Server, ruft ein Werkzeug auf und gibt dessen Antwort als dict zurück."""
    async with client.session("localmail") as session:
        result = await session.call_tool(name, arguments)
    text = "".join(getattr(part, "text", "") for part in result.content)
    if result.isError:
        raise RuntimeError(f"MCP-Werkzeug {name} fehlgeschlagen: {text}")
    return json.loads(text) if text else {}


def call_tool(name, arguments):
    """Dasselbe für normalen (nicht asynchronen) Code, z. B. call_tool("apply_label", {...}).

    In einem Notebook stattdessen: await call_tool_async(...)
    """
    return asyncio.run(call_tool_async(name, arguments))
