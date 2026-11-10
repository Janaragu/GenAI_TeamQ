"""Ruft die Werkzeuge des MCP-Servers auf (stdio, ein Serverprozess pro Aufruf)."""

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def _call(name: str, arguments: dict) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(ROOT),
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
    text = "".join(getattr(part, "text", "") for part in result.content)
    if result.isError:
        raise RuntimeError(f"MCP-Werkzeug {name} fehlgeschlagen: {text}")
    # FastMCP liefert Rückgaben vom Typ dict als JSON-Text, nicht als structuredContent.
    return result.structuredContent or (json.loads(text) if text else {})


def call_tool(name: str, arguments: dict) -> dict:
    """Synchroner Aufruf. Der eigene Thread macht ihn auch in Notebooks nutzbar."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(_call(name, arguments))).result()
