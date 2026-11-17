"""Was das LLM pro Mail zurückgeben muss (strukturierte Ausgabe).

Gleiches Prinzip wie die Klassen Classification und AgentResponse im Notebook 05:
Das LLM füllt dieses Schema aus, wir bekommen ein fertiges Python-Objekt zurück.
Die Texte bei description liest das LLM mit, sie gehören also zum Prompt.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Die fünf Kategorien. Zu jeder gehört ein Gmail-Label, z. B. "termin" -> "LocalMail/Termin".
#   termin      enthält einen konkreten Termin
#   aufgabe     verlangt eine Handlung oder Antwort
#   info        persönlich relevant, keine Handlung nötig
#   newsletter  Massenversand, Werbung, Abos
#   spam        Betrug, Phishing, unerwünscht
CATEGORIES = ["termin", "aufgabe", "info", "newsletter", "spam"]


class EventProposal(BaseModel):
    """Ein Termin, den das LLM in der Mail gefunden hat."""

    title: str = Field(description="Kurzer Titel des Termins")
    start: datetime = Field(description="Beginn als ISO-8601, Ortszeit, ohne Zeitzone")
    end: datetime | None = Field(default=None, description="Ende, falls in der Mail genannt")
    location: str | None = Field(default=None, description="Ort, falls in der Mail genannt")


class EmailAnalysis(BaseModel):
    """Ergebnis der Analyse einer Mail."""

    category: Literal["termin", "aufgabe", "info", "newsletter", "spam"]
    summary: str = Field(description="Zusammenfassung in höchstens zwei Sätzen, auf Deutsch")
    event: EventProposal | None = Field(
        default=None,
        description="Nur ausfüllen, wenn die Mail einen konkreten Termin mit Datum nennt",
    )
