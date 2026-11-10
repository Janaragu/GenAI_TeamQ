"""Vergleicht System A (Regeln) und System B (LLM) auf dem Testset.

    python -m eval.metrics            # beide Systeme
    python -m eval.metrics --only-a   # nur Regeln, ohne LLM-Aufrufe
"""

import argparse
import json
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from eval.system_a import classify
from schemas import Category, Email

load_dotenv()


def load_testset() -> list[dict]:
    path = Path(os.getenv("TESTSET_PATH", "eval/data/testmails.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def scores(expected: list[Category], predicted: list[Category]) -> dict:
    accuracy = sum(e == p for e, p in zip(expected, predicted)) / len(expected)
    per_class = {}
    for category in Category:
        tp = sum(e == category and p == category for e, p in zip(expected, predicted))
        fp = sum(e != category and p == category for e, p in zip(expected, predicted))
        fn = sum(e == category and p != category for e, p in zip(expected, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[category.value] = {"precision": precision, "recall": recall, "f1": f1}
    macro_f1 = sum(c["f1"] for c in per_class.values()) / len(per_class)
    return {"accuracy": accuracy, "macro_f1": macro_f1, "per_class": per_class}


def evaluate(name: str, items: list[dict], predict: Callable[[Email], Category | None]) -> None:
    emails = [Email.model_validate(item["email"]) for item in items]
    expected = [Category(item["expected_category"]) for item in items]
    predicted = [predict(email) for email in emails]
    result = scores(expected, predicted)

    print(f"\n=== {name} ===")
    print(f"Accuracy: {result['accuracy']:.2f}   Macro-F1: {result['macro_f1']:.2f}")
    for category, c in result["per_class"].items():
        print(f"  {category:<11} P={c['precision']:.2f} R={c['recall']:.2f} F1={c['f1']:.2f}")
    for email, e, p in zip(emails, expected, predicted):
        if e != p:
            got = p.value if p else "vom Inhaltsfilter blockiert"
            print(f"  FEHLER {email.id}: erwartet {e.value}, erhalten {got} ({email.subject})")


def evaluate_llm(items: list[dict]) -> None:
    from agent.graph import analyze_email

    def analyze(email: Email):
        # Vom Inhaltsfilter blockierte Mails zählen als Fehler, statt den Lauf abzubrechen.
        try:
            return analyze_email(email)
        except Exception as error:
            if "content management policy" in str(error):
                return None
            raise

    emails = [Email.model_validate(item["email"]) for item in items]
    with ThreadPoolExecutor(max_workers=4) as pool:
        analyses = dict(zip((e.id for e in emails), pool.map(analyze, emails)))
    evaluate(
        "System B (LLM)",
        items,
        lambda email: analyses[email.id].category if analyses[email.id] else None,
    )
    hits = sum(
        bool(analyses[i["email"]["id"]] and analyses[i["email"]["id"]].event)
        == i["expected_has_event"]
        for i in items
    )
    print(f"Termin erkannt ja/nein korrekt: {hits}/{len(items)}")


def main() -> None:
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
