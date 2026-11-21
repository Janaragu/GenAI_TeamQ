"""Lässt ein Modell alle Mails aus eval/modellvergleich/mails.json einordnen und stoppt die Zeit.

    python -m eval.modellvergleich.run_model --backend ollama   --model qwen3.5:4b
    python -m eval.modellvergleich.run_model --backend lmstudio --model google/gemma-4-12b-qat
    python -m eval.modellvergleich.run_model --backend cloud    --model gpt-6-luna

Nutzt dieselbe Funktion wie die App (agent.graph.analyze_email): gleicher Prompt, gleiches
Schema, gleiche Einstellungen. Ohne Nebenwirkungen: kein Label, kein Kalendereintrag.
Die Mails laufen nacheinander (1 Anfrage gleichzeitig), damit die Zeit pro Mail sauber ist.
Jeder Lauf schreibt eine neue Datei mit Zeitstempel, nichts wird überschrieben.
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from agent import llm

HERE = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["cloud", *llm.LOCAL], required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    if args.backend == "cloud":
        llm.engine = {**llm.cloud_from_env(), "model": args.model}
    else:
        llm.engine = {"provider": args.backend, "base_url": llm.local_url(args.backend), "model": args.model, "api_key": ""}
    problem = llm.engine_problem()
    if problem:
        raise SystemExit(problem)

    from agent.graph import analyze_email  # erst nach dem Setzen der Engine laden

    mails = json.loads((HERE / "mails.json").read_text(encoding="utf-8"))
    print(f"{args.model} über {args.backend}: {len(mails)} Mails", flush=True)

    # Aufwärmen: Die erste Anfrage lädt ein lokales Modell in den Speicher, das zählt nicht mit.
    warm_start = time.perf_counter()
    analyze_email(mails[0])
    warmup_seconds = round(time.perf_counter() - warm_start, 2)

    rows = []
    run_start = time.perf_counter()
    for nr, mail in enumerate(mails, 1):
        start = time.perf_counter()
        try:
            analysis = analyze_email(mail)
            result = {
                "category": analysis.category,
                "event_start": analysis.event.start.isoformat(timespec="minutes") if analysis.event else None,
                "event_title": analysis.event.title if analysis.event else None,
                "summary": analysis.summary,
                "error": None,
            }
        except Exception as exc:  # ein Fehler zählt als Fehler, bricht den Lauf aber nicht ab
            result = {"category": None, "event_start": None, "event_title": None, "summary": None,
                      "error": f"{type(exc).__name__}: {exc}"[:300]}
        seconds = round(time.perf_counter() - start, 2)
        rows.append({"nr": nr, "id": mail["id"], "subject": mail["subject"], "seconds": seconds, **result})
        print(f"{nr:02d} {seconds:6.2f}s {result['category']!s:10} {mail['subject'][:50]}", flush=True)

    report = {
        "backend": args.backend,
        "model": args.model,
        "date": datetime.now().isoformat(timespec="seconds"),
        "mode": "nacheinander, 1 Anfrage gleichzeitig",
        "warmup_seconds": warmup_seconds,
        "total_seconds": round(time.perf_counter() - run_start, 1),
        "rows": rows,
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = HERE / "results" / f"{args.backend}_{args.model.replace('/', '_').replace(':', '_')}_{stamp}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gespeichert: {path}", flush=True)


if __name__ == "__main__":
    main()
