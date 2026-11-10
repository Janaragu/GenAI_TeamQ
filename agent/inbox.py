"""Holt neue Mails und ordnet sie automatisch zu."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from agent import store
from agent.graph import run_agent
from agent.tools import call_tool
from schemas import Email

MAX_WORKERS = 4
_lock = threading.Lock()


@dataclass
class SyncResult:
    new: int = 0
    failed: int = 0
    busy: bool = False


def source_name(use_testset: bool) -> str:
    return "test" if use_testset else "gmail"


def _fetch_new(use_testset: bool, limit: int) -> list[Email]:
    known = store.known_ids(source_name(use_testset))
    if use_testset:
        path = Path(os.getenv("TESTSET_PATH", "eval/data/testmails.json"))
        items = json.loads(path.read_text(encoding="utf-8"))
        emails = [Email.model_validate(item["email"]) for item in items]
        return [email for email in emails if email.id not in known][:limit]

    ids = call_tool("list_email_ids", {"query": "in:inbox", "max_results": limit})["ids"]
    new_ids = [email_id for email_id in ids if email_id not in known]
    if not new_ids:
        return []
    raw = call_tool("get_emails", {"ids": new_ids})["emails"]
    return [Email.model_validate(item) for item in raw]


def _process(email: Email, use_testset: bool) -> bool:
    source = source_name(use_testset)
    try:
        run_agent(email, dry_run=use_testset)
        return True
    except Exception as error:
        # Der Inhaltsfilter blockiert dieselbe Mail immer wieder, also nicht erneut versuchen.
        # Andere Fehler (z. B. Netzwerk) werden beim nächsten Abruf wiederholt.
        if "content management policy" in str(error):
            store.save_failed(email, source, "Vom Inhaltsfilter des LLM blockiert.")
        return False


def sync(use_testset: bool, limit: int = 25) -> SyncResult:
    """Verarbeitet alle neuen Mails. Läuft schon ein Abruf, passiert nichts."""
    if not _lock.acquire(blocking=False):
        return SyncResult(busy=True)
    try:
        emails = _fetch_new(use_testset, limit)
        if not emails:
            return SyncResult()
        store.log(
            "abgerufen", details=f"{len(emails)} neue Mails", source=source_name(use_testset)
        )
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            outcomes = list(pool.map(lambda email: _process(email, use_testset), emails))
        return SyncResult(new=sum(outcomes), failed=len(outcomes) - sum(outcomes))
    finally:
        _lock.release()
