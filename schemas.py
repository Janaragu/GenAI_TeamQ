"""Gemeinsame Pydantic-Schemas: die Schnittstelle zwischen Agent, MCP-Server, UI und Evaluation."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    TERMIN = "termin"          # enthält einen konkreten Termin
    AUFGABE = "aufgabe"        # verlangt eine Handlung oder Antwort
    INFO = "info"              # persönlich relevant, keine Handlung nötig
    NEWSLETTER = "newsletter"  # Massenversand, Werbung, Abos
    SPAM = "spam"              # Betrug, Phishing, unerwünscht

    @property
    def label(self) -> str:
        """Gmail-Label, das zu dieser Kategorie gehört."""
        return f"LocalMail/{self.value.capitalize()}"


class Email(BaseModel):
    id: str
    thread_id: str = ""
    sender: str
    subject: str
    body: str
    received_at: datetime | None = None


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


class AgentStatus(str, Enum):
    DONE = "done"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


class AgentResult(BaseModel):
    email_id: str
    subject: str = ""
    status: AgentStatus
    analysis: EmailAnalysis
    label_applied: str | None = None
    event_created: bool = False
    event_link: str | None = None
