"""Gemeinsame Datenmodelle (Pydantic) für das ganze Projekt.

Alle Teile (Agent, MCP-Server, Oberfläche, Evaluation) tauschen Daten in diesen
Formen aus. Ändert ihr hier etwas, betrifft das alle anderen Teile.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Kategorien: In genau eine davon sortiert der Agent jede Mail ein.
# Jede Kategorie hat ein passendes Gmail-Label, z. B. "LocalMail/Termin".
# -----------------------------------------------------------------------------
class Category(str, Enum):
    TERMIN = "termin"          # enthält einen konkreten Termin
    AUFGABE = "aufgabe"        # verlangt eine Handlung oder Antwort
    INFO = "info"              # persönlich relevant, keine Handlung nötig
    NEWSLETTER = "newsletter"  # Massenversand, Werbung, Abos
    SPAM = "spam"              # Betrug, Phishing, unerwünscht

    @property
    def label(self) -> str:
        """Name des Gmail-Labels zu dieser Kategorie."""
        return f"LocalMail/{self.value.capitalize()}"


# -----------------------------------------------------------------------------
# Eine Mail, so wie sie aus Gmail (oder aus dem Testset) kommt.
# -----------------------------------------------------------------------------
class Email(BaseModel):
    id: str
    thread_id: str = ""
    sender: str
    subject: str
    body: str
    received_at: datetime | None = None


# -----------------------------------------------------------------------------
# Was das LLM zurückgibt. Die Beschreibungen (description) liest das LLM mit,
# sie sind also Teil des Prompts.
# -----------------------------------------------------------------------------
class EventProposal(BaseModel):
    title: str = Field(description="Kurzer Titel des Termins")
    start: datetime = Field(description="Beginn als ISO-8601, Ortszeit, ohne Zeitzone")
    end: datetime | None = Field(default=None, description="Ende, falls in der Mail genannt")
    location: str | None = Field(default=None, description="Ort, falls in der Mail genannt")


class EmailAnalysis(BaseModel):
    """Strukturierte Ausgabe des LLM für eine Mail."""

    category: Category
    summary: str = Field(description="Zusammenfassung in höchstens zwei Sätzen, auf Deutsch")
    event: EventProposal | None = Field(
        default=None,
        description="Nur ausfüllen, wenn die Mail einen konkreten Termin mit Datum nennt",
    )


# -----------------------------------------------------------------------------
# Ergebnis eines Agenten-Laufs für eine Mail. Die Oberfläche zeigt das an.
# -----------------------------------------------------------------------------
class AgentStatus(str, Enum):
    DONE = "done"                                    # fertig verarbeitet
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # Termin wartet auf Ja/Nein


class AgentResult(BaseModel):
    email_id: str
    subject: str = ""
    status: AgentStatus
    analysis: EmailAnalysis
    label_applied: str | None = None
    event_created: bool = False
    event_link: str | None = None
