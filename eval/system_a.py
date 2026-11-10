"""System A: regelbasierte Baseline (Schlüsselwörter), Vergleichsmassstab für den LLM-Agenten."""

from schemas import Category, Email

SPAM = ("gewonnen", "lotterie", "konto gesperrt", "bestätigen sie ihre daten", "bitcoin", "erbschaft")
NEWSLETTER = ("newsletter", "abmelden", "unsubscribe", "% rabatt", "angebot der woche")
TERMIN = ("einladung", "termin am", "sitzung am", "besprechung am", "uhr im", "uhr in")
AUFGABE = ("bitte", "frist", "bis spätestens", "rechnung", "benötigen wir", "kannst du")


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
