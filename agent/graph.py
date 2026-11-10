"""LangGraph-Agent: analysieren, labeln, Termin bestätigen lassen, eintragen."""

import os
import sqlite3
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent import store
from agent.llm import get_llm
from agent.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from agent.state import AgentState
from agent.tools import call_tool
from schemas import AgentResult, AgentStatus, Category, Email, EmailAnalysis

load_dotenv()

MAX_BODY_CHARS = 6000


def analyze_email(email: Email) -> EmailAnalysis:
    """Reine Analyse ohne Nebenwirkungen. Wird auch von der Evaluation benutzt."""
    llm = get_llm().with_structured_output(EmailAnalysis)
    user = USER_TEMPLATE.format(
        received_at=email.received_at.isoformat() if email.received_at else "unbekannt",
        sender=email.sender,
        subject=email.subject,
        body=email.body[:MAX_BODY_CHARS],
    )
    analysis = llm.invoke([("system", SYSTEM_PROMPT), ("user", user)])
    if analysis.category is not Category.TERMIN:
        analysis.event = None
    elif analysis.event:
        # Uhrzeiten aus Mails sind Ortszeit. Das Modell hängt trotzdem oft "Z" an.
        event = analysis.event
        event.start = event.start.replace(tzinfo=None)
        event.end = event.end.replace(tzinfo=None) if event.end else None
    return analysis


def _source(dry_run: bool | None) -> str:
    return "test" if dry_run else "gmail"


def _log(state: AgentState, action: str, details: str, actor: str = "agent") -> None:
    email = state["email"]
    store.log(action, email["id"], email["subject"], details, _source(state.get("dry_run")), actor)


def _analyze(state: AgentState) -> AgentState:
    analysis = analyze_email(Email.model_validate(state["email"]))
    _log(state, "analysiert", f"Kategorie {analysis.category.value}, Modell {get_llm().model_name}")
    return {"analysis": analysis.model_dump(mode="json")}


def _apply_label(state: AgentState) -> AgentState:
    label = Category(state["analysis"]["category"]).label
    if not state.get("dry_run"):
        call_tool("apply_label", {"message_id": state["email"]["id"], "label_name": label})
    _log(state, "zugeordnet", label)
    event = state["analysis"].get("event")
    if event:
        _log(state, "termin_vorgeschlagen", f"{event['title']}, {event['start']}")
    return {"label_applied": label}


def _after_label(state: AgentState) -> str:
    return "confirm_event" if state["analysis"].get("event") else END


def _confirm_event(state: AgentState) -> AgentState:
    # Beim Fortsetzen läuft der Knoten neu an, deshalb steht vor interrupt() nichts.
    approved = interrupt({"event": state["analysis"]["event"]})
    action = "termin_bestaetigt" if approved else "termin_verworfen"
    _log(state, action, state["analysis"]["event"]["title"], actor="nutzer")
    return {"event_approved": bool(approved)}


def _after_confirm(state: AgentState) -> str:
    return "create_event" if state.get("event_approved") else END


def _create_event(state: AgentState) -> AgentState:
    if state.get("dry_run"):
        _log(state, "termin_eingetragen", "Testlauf, nichts in den Kalender geschrieben")
        return {"event_link": "(Testlauf, nichts eingetragen)"}
    event = state["analysis"]["event"]
    start = datetime.fromisoformat(event["start"])
    end = datetime.fromisoformat(event["end"]) if event.get("end") else start + timedelta(hours=1)
    created = call_tool(
        "create_calendar_event",
        {
            "title": event["title"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "location": event.get("location"),
            "description": state["analysis"]["summary"],
        },
    )
    _log(state, "termin_eingetragen", created.get("link", ""))
    return {"event_link": created.get("link")}


@lru_cache(maxsize=1)
def get_graph():
    builder = StateGraph(AgentState)
    builder.add_node("analyze", _analyze)
    builder.add_node("apply_label", _apply_label)
    builder.add_node("confirm_event", _confirm_event)
    builder.add_node("create_event", _create_event)
    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", "apply_label")
    builder.add_conditional_edges("apply_label", _after_label, ["confirm_event", END])
    builder.add_conditional_edges("confirm_event", _after_confirm, ["create_event", END])
    builder.add_edge("create_event", END)

    path = Path(os.getenv("SQLITE_PATH", "data/localmail.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    return builder.compile(checkpointer=SqliteSaver(connection))


def _config(email_id: str, dry_run: bool) -> dict:
    prefix = "dry-" if dry_run else ""
    return {"configurable": {"thread_id": f"{prefix}{email_id}"}}


def _result(config: dict) -> AgentResult:
    snapshot = get_graph().get_state(config)
    values = snapshot.values
    return AgentResult(
        email_id=values["email"]["id"],
        subject=values["email"]["subject"],
        status=AgentStatus.AWAITING_CONFIRMATION if snapshot.next else AgentStatus.DONE,
        analysis=EmailAnalysis.model_validate(values["analysis"]),
        label_applied=values.get("label_applied"),
        event_created=bool(values.get("event_link")),
        event_link=values.get("event_link"),
    )


def run_agent(email: Email, dry_run: bool = False) -> AgentResult:
    """Verarbeitet eine Mail. Bereits verarbeitete Mails liefern das gespeicherte Ergebnis."""
    graph = get_graph()
    config = _config(email.id, dry_run)
    snapshot = graph.get_state(config)
    already_handled = snapshot.values.get("label_applied") and (
        not snapshot.next or snapshot.next == ("confirm_event",)
    )
    if not already_handled:
        try:
            graph.invoke({"email": email.model_dump(mode="json"), "dry_run": dry_run}, config)
        except Exception as error:
            store.log("fehler", email.id, email.subject, str(error)[:300], _source(dry_run))
            raise
    else:
        store.log("uebernommen", email.id, email.subject, "Bereits früher verarbeitet", _source(dry_run))
    result = _result(config)
    store.save_result(email, result, _source(dry_run))
    return result


def resume_agent(email_id: str, approved: bool, dry_run: bool = False) -> AgentResult:
    """Setzt nach der Entscheidung über einen Terminvorschlag fort."""
    config = _config(email_id, dry_run)
    try:
        get_graph().invoke(Command(resume=approved), config)
    except Exception as error:
        store.log("fehler", email_id, details=str(error)[:300], source=_source(dry_run))
        raise
    result = _result(config)
    store.update_after_decision(result)
    return result
