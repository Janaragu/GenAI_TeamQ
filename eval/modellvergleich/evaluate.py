"""Vergleicht die neuesten Ergebnisse jedes Modells mit der Baseline (Opus 5.5).

    python -m eval.modellvergleich.evaluate

Kennzahlen pro Modell:
  - Übereinstimmung mit der Baseline: alle Mails, nur klare Fälle, ohne Duplikate
  - Termine: erkannt und mit richtigem Startdatum/-zeit
  - Falsche Termine: Terminvorschlag bei einer Mail, die laut Baseline kein Termin ist
  - Zeit: Summe, Median, Maximum pro Mail
Schreibt eval/modellvergleich/auswertung.json.
"""

import json
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
DUPLICATES = {36, 37, 38, 39, 40}  # Kopien von Nr. 31 bis 35


def latest_results():
    newest = {}
    for path in sorted((HERE / "results").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        newest[data["model"]] = (path.name, data)  # sortiert nach Zeitstempel: der letzte gewinnt
    return newest


def evaluate(baseline, data):
    rows = {r["nr"]: r for r in data["rows"]}
    agree, agree_clear, agree_unique = [], [], []
    events_ok, events_found, false_events, wrong = 0, 0, [], []
    confusion = Counter()
    for label in baseline:
        row = rows[label["nr"]]
        same = row["category"] == label["category"]
        agree.append(same)
        if label["certainty"] == "klar":
            agree_clear.append(same)
        if label["nr"] not in DUPLICATES:
            agree_unique.append(same)
        if not same:
            confusion[(label["category"], row["category"])] += 1
            wrong.append({"nr": label["nr"], "subject": row["subject"], "baseline": label["category"],
                          "model": row["category"], "certainty": label["certainty"]})
        if label["category"] == "termin":
            if row["event_start"]:
                events_found += 1
                if row["event_start"][:16] == label["event_start"]:
                    events_ok += 1
        elif row["event_start"]:
            false_events.append({"nr": label["nr"], "subject": row["subject"], "event_start": row["event_start"]})

    seconds = [r["seconds"] for r in data["rows"]]
    termine = sum(1 for label in baseline if label["category"] == "termin")
    return {
        "model": data["model"],
        "backend": data["backend"],
        "agree_all": f"{sum(agree)}/{len(agree)}",
        "agree_all_pct": round(100 * sum(agree) / len(agree), 1),
        "agree_clear": f"{sum(agree_clear)}/{len(agree_clear)}",
        "agree_clear_pct": round(100 * sum(agree_clear) / len(agree_clear), 1),
        "agree_unique": f"{sum(agree_unique)}/{len(agree_unique)}",
        "events_found": f"{events_found}/{termine}",
        "events_exact": f"{events_ok}/{termine}",
        "false_events": false_events,
        "errors": [r["nr"] for r in data["rows"] if r["error"]],
        "seconds_total": round(sum(seconds), 1),
        "seconds_mean": round(statistics.mean(seconds), 2),
        "seconds_median": round(statistics.median(seconds), 2),
        "seconds_max": max(seconds),
        "warmup_seconds": data["warmup_seconds"],
        "wrong": wrong,
        "confusion": {f"{a} -> {b}": n for (a, b), n in confusion.most_common()},
    }


def main():
    baseline = json.loads((HERE / "baseline_opus-5.5.json").read_text(encoding="utf-8"))["labels"]
    report = {}
    for model, (name, data) in latest_results().items():
        report[model] = {"file": name, **evaluate(baseline, data)}
        r = report[model]
        print(f"\n== {model} ({name})")
        print(f"Übereinstimmung: alle {r['agree_all']} ({r['agree_all_pct']} %), klare Fälle {r['agree_clear']}, ohne Duplikate {r['agree_unique']}")
        print(f"Termine erkannt {r['events_found']}, exakt {r['events_exact']}, falsche Termine {len(r['false_events'])}, Fehler {r['errors']}")
        print(f"Zeit: Summe {r['seconds_total']} s, Median {r['seconds_median']} s, Max {r['seconds_max']} s, Aufwärmen {r['warmup_seconds']} s")
        for w in r["wrong"]:
            print(f"  Nr. {w['nr']:2} {w['baseline']:>10} -> {w['model']!s:10} ({w['certainty']}) {w['subject'][:50]}")
        for f in r["false_events"]:
            print(f"  FALSCHER TERMIN Nr. {f['nr']}: {f['event_start']} {f['subject'][:50]}")
    (HERE / "auswertung.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
