"""System A: einfache Regeln mit Schlüsselwörtern, ohne KI.

Dient als Vergleich: Ist der LLM-Agent (System B) wirklich besser als ein paar
feste Regeln? Die Regeln werden der Reihe nach geprüft, der erste Treffer gewinnt.
Passt nichts, wird es "info".
"""

# Schlüsselwörter pro Kategorie (klein geschrieben), in der Reihenfolge der Prüfung
RULES = [
    ("spam", ["gewonnen", "lotterie", "konto gesperrt", "bestätigen sie ihre daten", "bitcoin", "erbschaft"]),
    ("newsletter", ["newsletter", "abmelden", "unsubscribe", "% rabatt", "angebot der woche"]),
    ("termin", ["einladung", "termin am", "sitzung am", "besprechung am", "uhr im", "uhr in"]),
    ("aufgabe", ["bitte", "frist", "bis spätestens", "rechnung", "benötigen wir", "kannst du"]),
]


def classify(email):
    """Betreff und Text durchsuchen, erster Treffer gewinnt."""
    text = f"{email['subject']} {email['body']}".lower()
    for category, keywords in RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "info"
