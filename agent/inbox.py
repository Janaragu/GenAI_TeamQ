"""Holt neue Mails und lässt sie vom Agenten automatisch einsortieren.

Die Oberfläche ruft sync() beim Öffnen und danach jede Minute auf:
  1. neue Mails holen und sofort speichern (Status "pending"), damit sie sichtbar sind
  2. wartende Mails vom Agenten analysieren lassen, sofern eine KI-Engine bereit ist
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent import store
from agent.graph import run_agent
from agent.tools import call_tool

MAX_WORKERS = 4           # so viele Mails werden gleichzeitig analysiert
lock = threading.Lock()   # verhindert, dass zwei Abrufe gleichzeitig laufen


def source_name(use_testset):
    return "test" if use_testset else "gmail"


# -----------------------------------------------------------------------------
# 1. Neue Mails holen: nur solche, die noch nicht in der Datenbank sind.
#    Testmodus: aus eval/data/testmails.json. Sonst: neueste Mails aus Gmail.
# -----------------------------------------------------------------------------
def fetch_new(use_testset, limit):
    known = store.known_ids(source_name(use_testset))

    if use_testset:
        path = Path(os.getenv("TESTSET_PATH", "eval/data/testmails.json"))
        items = json.loads(path.read_text(encoding="utf-8"))
        return [item["email"] for item in items if item["email"]["id"] not in known][:limit]

    ids = call_tool("list_email_ids", {"query": "in:inbox", "max_results": limit})["ids"]
    new_ids = [email_id for email_id in ids if email_id not in known]
    if not new_ids:
        return []
    return call_tool("get_emails", {"ids": new_ids})["emails"]


# -----------------------------------------------------------------------------
# 2. Eine Mail verarbeiten. Ein Fehler stoppt nicht den ganzen Abruf.
# -----------------------------------------------------------------------------
def process(email, use_testset):
    """Gibt True zurück, wenn die Mail analysiert wurde."""
    try:
        run_agent(email, dry_run=use_testset)
        return True
    except Exception as error:
        # Der Inhaltsfilter blockiert dieselbe Mail immer wieder, also nicht erneut versuchen.
        # Andere Fehler (z. B. Netzwerk) bleiben "pending" und werden beim nächsten Abruf wiederholt.
        if "content management policy" in str(error):
            store.save_failed(email["id"], "Vom Inhaltsfilter des LLM blockiert.")
        return False


# -----------------------------------------------------------------------------
# 3. Abruf. analyze=False (KI-Engine nicht bereit): nur abrufen und anzeigen.
#    Rückgabe:
#      new      erfolgreich analysierte Mails
#      failed   Mails mit Fehler
#      busy     True, wenn schon ein Abruf lief
#      fetched  neu abgerufene Mails
#      pending  Mails, die danach noch auf die Analyse warten
# -----------------------------------------------------------------------------
def sync(use_testset, limit=25, analyze=True):
    result = {"new": 0, "failed": 0, "busy": False, "fetched": 0, "pending": 0}
    if not lock.acquire(blocking=False):
        result["busy"] = True
        return result

    try:
        source = source_name(use_testset)
        result["fetched"] = store.save_new(fetch_new(use_testset, limit), source)
        if result["fetched"]:
            store.log("abgerufen", details=f"{result['fetched']} neue Mails", source=source)

        if not analyze:
            result["pending"] = len(store.pending_emails(source, 10_000))
            return result

        emails = store.pending_emails(source, limit)
        if not emails:
            return result

        # Mehrere Mails gleichzeitig: Jede wartet die meiste Zeit auf das LLM.
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            outcomes = list(pool.map(lambda email: process(email, use_testset), emails))
        result["new"] = sum(outcomes)
        result["failed"] = len(outcomes) - sum(outcomes)
        result["pending"] = len(store.pending_emails(source, 10_000))
        return result
    finally:
        lock.release()
