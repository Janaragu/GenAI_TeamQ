"""Zustand des LangGraph-Graphen. Nur JSON-fähige Werte, damit Checkpoints robust bleiben."""

from typing import TypedDict


class AgentState(TypedDict, total=False):
    email: dict
    dry_run: bool
    analysis: dict
    label_applied: str | None
    event_approved: bool
    event_link: str | None
