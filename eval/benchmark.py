"""Misst ein lokales Modell auf dem Testset: Fehlerquote UND Zeit pro Mail.

    python -m eval.benchmark --backend ollama   --model qwen3.5:4b
    python -m eval.benchmark --backend lmstudio --model google/gemma-4-12b-qat

Zwei Durchläufe über alle Testmails:
  1. nacheinander (1 Anfrage gleichzeitig): saubere Zeit pro Mail
  2. parallel (--workers, Standard 4 wie in agent/inbox.py): so arbeitet die App

Das Ergebnis landet als JSON in eval/results/, damit man Modelle vergleichen kann.
Anders als eval/metrics.py misst dieses Skript auch die Zeit.
"""

import argparse
import json
import platform
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from agent import llm
from agent.graph import MAX_BODY_CHARS
from eval.metrics import load_testset, scores

RESULTS = Path("eval/results")


# -----------------------------------------------------------------------------
# 1. Eine Mail analysieren und die Zeit stoppen. Fehler zählen, nicht abbrechen.
# -----------------------------------------------------------------------------
def timed_analysis(item):
    from agent.graph import analyze_email  # erst hier laden, nach dem Setzen der Engine

    start = time.perf_counter()
    try:
        analysis = analyze_email(item["email"])
        error = None
    except Exception as exc:
        analysis, error = None, f"{type(exc).__name__}: {exc}"[:200]
    return {
        "id": item["email"]["id"],
        "seconds": round(time.perf_counter() - start, 2),
        "expected": item["expected_category"],
        "got": analysis.category if analysis else None,
        "expected_event": item["expected_has_event"],
        "got_event": bool(analysis and analysis.event),
        "error": error,
    }


# -----------------------------------------------------------------------------
# 2. Kennzahlen aus den Einzelergebnissen
# -----------------------------------------------------------------------------
def summarize(rows, wall_seconds):
    result = scores([r["expected"] for r in rows], [r["got"] for r in rows])
    times = [r["seconds"] for r in rows]
    return {
        "accuracy": round(result["accuracy"], 3),
        "macro_f1": round(result["macro_f1"], 3),
        "wrong": [f"{r['id']}: erwartet {r['expected']}, erhalten {r['got']}" for r in rows if r["expected"] != r["got"]],
        "event_correct": sum(r["expected_event"] == r["got_event"] for r in rows),
        "errors": [f"{r['id']}: {r['error']}" for r in rows if r["error"]],
        "wall_seconds": round(wall_seconds, 1),      # Gesamtzeit des Durchlaufs
        "seconds_per_mail": round(wall_seconds / len(rows), 2),
        "median_seconds": round(statistics.median(times), 2),
        "max_seconds": max(times),
    }


def run(items, workers):
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(timed_analysis, items))
    return rows, summarize(rows, time.perf_counter() - start)


# -----------------------------------------------------------------------------
# 3. Start: Engine setzen, aufwärmen, zwei Durchläufe, speichern
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=llm.LOCAL, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    llm.engine = {"provider": args.backend, "base_url": llm.local_url(args.backend), "model": args.model, "api_key": ""}
    problem = llm.engine_problem()
    if problem:
        raise SystemExit(problem)

    items = load_testset()
    print(f"{args.model} über {args.backend}, {len(items)} Testmails")

    # Aufwärmen: Die erste Anfrage lädt das Modell in den Speicher, das soll nicht mitzählen.
    timed_analysis(items[0])

    rows, sequential = run(items, workers=1)
    print("nacheinander:", json.dumps(sequential, ensure_ascii=False))
    _, parallel = run(items, workers=args.workers)
    print(f"{args.workers} parallel:", json.dumps(parallel, ensure_ascii=False))

    report = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "backend": args.backend,
        "model": args.model,
        "settings": {  # was in agent/llm.py und agent/graph.py eingestellt ist
            "temperature": 0,
            "reasoning_effort": "none",
            "structured_output": "json_schema",
            "max_body_chars": MAX_BODY_CHARS,
            "workers_parallel": args.workers,
        },
        "machine": {
            "chip": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip(),
            "system": platform.platform(),
        },
        "sequential": sequential,
        "parallel": parallel,
        "per_mail": rows,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.backend}_{args.model.replace('/', '_').replace(':', '_')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gespeichert: {path}")


if __name__ == "__main__":
    main()
