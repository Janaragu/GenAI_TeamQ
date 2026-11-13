"""Der Zustand (State), den LangGraph zwischen den Schritten weiterreicht.

Jeder Knoten im Graphen liest daraus und gibt Änderungen zurück. LangGraph
speichert den Zustand nach jedem Schritt in SQLite (Checkpoint). Darum stehen
hier nur einfache Werte (dict, str, bool), die sich problemlos speichern lassen.
"""

from typing import TypedDict


class AgentState(TypedDict, total=False):
    email: dict                # die Mail (Email als dict)
    dry_run: bool              # True = Testlauf, nichts in Gmail/Kalender schreiben
    analysis: dict             # Ergebnis des LLM (EmailAnalysis als dict)
    label_applied: str | None  # gesetztes Gmail-Label
    event_approved: bool       # Entscheidung des Nutzers zum Terminvorschlag
    event_link: str | None     # Link zum Kalendereintrag
