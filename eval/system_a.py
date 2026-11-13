"""System A: einfache Regeln mit Schlüsselwörtern, ohne KI.

Dient als Vergleich: Ist der LLM-Agent (System B) wirklich besser als ein
paar feste Regeln? Die Regeln werden der Reihe nach geprüft, der erste
Treffer gewinnt. Passt nichts, wird es "info".
"""

from schemas import Category, Email

# -----------------------------------------------------------------------------
# Schlüsselwörter pro Kategorie (klein geschrieben)
# -----------------------------------------------------------------------------
SPAM = ("gewonnen", "lotterie", "konto gesperrt", "bestätigen sie ihre daten", "bitcoin", "erbschaft")
NEWSLETTER = ("newsletter", "abmelden", "unsubscribe", "% rabatt", "angebot der woche")
TERMIN = ("einladung", "termin am", "sitzung am", "besprechung am", "uhr im", "uhr in")
AUFGABE = ("bitte", "frist", "bis spätestens", "rechnung", "benötigen wir", "kannst du")


# -----------------------------------------------------------------------------
# Klassifizieren: Betreff und Text durchsuchen, erster Treffer gewinnt.
# -----------------------------------------------------------------------------
def classify(email: Email) -> Category:
    text = f"{email.subject} {email.body}".lower()
    for keywords, category in (
        (SPAM, Category.SPAM),
        (NEWSLETTER, Category.NEWSLETTER),
        (TERMIN, Category.TERMIN),
        (AUFGABE, Category.AUFGABE),
    ):
        if any(keyword in text for keyword in keywords):
            return category
    return Category.INFO
