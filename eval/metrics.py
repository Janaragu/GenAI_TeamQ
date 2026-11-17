"""Vergleicht System A (Regeln) und System B (LLM) auf dem Testset.

    python -m eval.metrics            # beide Systeme
    python -m eval.metrics --only-a   # nur Regeln, ohne LLM-Aufrufe

Das Testset (eval/data/testmails.json) enthält Mails mit der richtigen Kategorie
("expected_category"). Gemessen wird, wie oft die Systeme richtig liegen.
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from eval.system_a import classify
from schemas import CATEGORIES

load_dotenv()


def load_testset():
    path = Path(os.getenv("TESTSET_PATH", "eval/data/testmails.json"))
    return json.loads(path.read_text(encoding="utf-8"))


# -----------------------------------------------------------------------------
# 1. Kennzahlen berechnen
#    Accuracy  = Anteil richtiger Antworten
#    Precision = von allen als X erkannten Mails: wie viele waren wirklich X?
#    Recall    = von allen echten X-Mails: wie viele wurden gefunden?
#    F1        = Mittel aus Precision und Recall, Macro-F1 = Schnitt über alle Kategorien
# -----------------------------------------------------------------------------
def scores(expected, predicted):
    pairs = list(zip(expected, predicted))
    accuracy = sum(e == p for e, p in pairs) / len(pairs)
    per_class = {}
    for category in CATEGORIES:
        tp = sum(e == category and p == category for e, p in pairs)  # richtig als X erkannt
        fp = sum(e != category and p == category for e, p in pairs)  # fälschlich als X erkannt
        fn = sum(e == category and p != category for e, p in pairs)  # X übersehen
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[category] = {"precision": precision, "recall": recall, "f1": f1}
    macro_f1 = sum(c["f1"] for c in per_class.values()) / len(per_class)
    return {"accuracy": accuracy, "macro_f1": macro_f1, "per_class": per_class}


# -----------------------------------------------------------------------------
# 2. Ein System auswerten und Ergebnis samt Fehlern ausgeben
#    predict bekommt eine Mail (dict) und gibt eine Kategorie zurück (oder None).
# -----------------------------------------------------------------------------
def evaluate(name, items, predict):
    emails = [item["email"] for item in items]
    expected = [item["expected_category"] for item in items]
    predicted = [predict(email) for email in emails]
    result = scores(expected, predicted)

    print(f"\n=== {name} ===")
    print(f"Accuracy: {result['accuracy']:.2f}   Macro-F1: {result['macro_f1']:.2f}")
    for category, c in result["per_class"].items():
        print(f"  {category:<11} P={c['precision']:.2f} R={c['recall']:.2f} F1={c['f1']:.2f}")
    for email, e, p in zip(emails, expected, predicted):
        if e != p:
            got = p or "vom Inhaltsfilter blockiert"
            print(f"  FEHLER {email['id']}: erwartet {e}, erhalten {got} ({email['subject']})")


# -----------------------------------------------------------------------------
# 3. System B: alle Mails vom LLM analysieren lassen (4 gleichzeitig)
# -----------------------------------------------------------------------------
def evaluate_llm(items):
    from agent.graph import analyze_email  # erst hier laden: --only-a braucht kein LLM

    def analyze(email):
        # Vom Inhaltsfilter blockierte Mails zählen als Fehler, statt den Lauf abzubrechen.
        try:
            return analyze_email(email)
        except Exception as error:
            if "content management policy" in str(error):
                return None
            raise

    emails = [item["email"] for item in items]
    with ThreadPoolExecutor(max_workers=4) as pool:
        analyses = dict(zip([e["id"] for e in emails], pool.map(analyze, emails)))

    def predict(email):
        analysis = analyses[email["id"]]
        return analysis.category if analysis else None

    evaluate("System B (LLM)", items, predict)

    hits = 0
    for item in items:
        analysis = analyses[item["email"]["id"]]
        found_event = bool(analysis and analysis.event)
        hits += found_event == item["expected_has_event"]
    print(f"Termin erkannt ja/nein korrekt: {hits}/{len(items)}")


# -----------------------------------------------------------------------------
# 4. Start über die Kommandozeile
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-a", action="store_true", help="nur System A, ohne LLM")
    args = parser.parse_args()

    items = load_testset()
    print(f"Testset: {len(items)} Mails")
    evaluate("System A (Regeln)", items, classify)
    if not args.only_a:
        evaluate_llm(items)


if __name__ == "__main__":
    main()
