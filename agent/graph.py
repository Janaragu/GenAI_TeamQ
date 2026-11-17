"""Der Agent als LangGraph-Graph (aufgebaut wie im Notebook 05).

Ablauf pro Mail:

    START -> analyze -> apply_label -> (Termin gefunden?) -> confirm_event -> (Ja?) -> create_event -> END
                                              | nein                              | nein
                                             END                                 END

analyze        das LLM liest die Mail und füllt EmailAnalysis aus (strukturierte Ausgabe)
apply_label    setzt das passende Gmail-Label über den MCP-Server
confirm_event  hält an (interrupt, wie "escalate" im Notebook 08) und wartet auf Ja/Nein
create_event   trägt den Termin über den MCP-Server in Google Kalender ein

Ein Checkpointer (SQLite) merkt sich den Stand jeder Mail. So kann ein Terminvorschlag
auch nach einem Neustart noch bestätigt werden.
"""

import sqlite3
from datetime import datetime, timedelta

from langchain.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from agent import llm, store
from agent.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from agent.tools import call_tool
from schemas import EmailAnalysis

MAX_BODY_CHARS = 6000  # lange Mails werden gekürzt, damit der Prompt klein bleibt


# -----------------------------------------------------------------------------
# 1. State: was der Graph von Knoten zu Knoten weiterreicht
#    Nur einfache Werte (dict, str, bool), damit der Checkpointer sie speichern kann.
# -----------------------------------------------------------------------------
class AgentState(TypedDict, total=False):
    email: dict           # die Mail: id, sender, subject, body, received_at
    dry_run: bool         # True = Testmodus, nichts in Gmail oder den Kalender schreiben
    analysis: dict        # Ergebnis des LLM (EmailAnalysis als dict)
    label_applied: str    # gesetztes Gmail-Label
    event_approved: bool  # Ja/Nein des Nutzers zum Terminvorschlag
    event_link: str       # Link zum Kalendereintrag


# -----------------------------------------------------------------------------
# 2. Analyse: die Mail ans LLM schicken
# -----------------------------------------------------------------------------
def analyze_email(email):
    """Schickt eine Mail ans LLM und gibt eine EmailAnalysis zurück.

    Ohne Nebenwirkungen, deshalb nutzt auch die Evaluation (eval/metrics.py) diese Funktion.
    """
    # Bei jedem Aufruf neu bauen, weil die Engine in der Oberfläche umstellbar ist.
    # method="json_schema": das Modell füllt das JSON-Schema von EmailAnalysis aus.
    analyzer = llm.get_llm().with_structured_output(EmailAnalysis, method="json_schema")
    mail_text = USER_TEMPLATE.format(
        received_at=email.get("received_at") or "unbekannt",
        sender=email["sender"],
        subject=email["subject"],
        body=email["body"][:MAX_BODY_CHARS],
    )
    analysis = analyzer.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=mail_text)])

    if analysis.category != "termin":
        analysis.event = None  # nur Termin-Mails bekommen einen Terminvorschlag
    elif analysis.event:
        # Uhrzeiten in Mails sind Ortszeit. Das Modell hängt trotzdem oft "Z" (UTC) an.
        analysis.event.start = analysis.event.start.replace(tzinfo=None)
        if analysis.event.end:
            analysis.event.end = analysis.event.end.replace(tzinfo=None)
    return analysis


def log(state, action, details, actor="agent"):
    """Schreibt einen Eintrag ins Protokoll (Tabelle activity_log)."""
    source = "test" if state.get("dry_run") else "gmail"
    store.log(action, state["email"]["id"], state["email"]["subject"], details, source, actor)


# -----------------------------------------------------------------------------
# 3. Die Knoten. Jeder bekommt den State und gibt nur die Felder zurück, die er ändert.
# -----------------------------------------------------------------------------
def analyze(state: AgentState):
    """Das LLM bestimmt Kategorie, Zusammenfassung und allenfalls einen Termin."""
    analysis = analyze_email(state["email"])
    log(state, "analysiert", f"Kategorie {analysis.category}, Modell {llm.engine['model']}")
    return {"analysis": analysis.model_dump(mode="json")}


def apply_label(state: AgentState):
    """Setzt das Gmail-Label der Kategorie, z. B. LocalMail/Spam. Im Testmodus nur so tun als ob."""
    label = f"LocalMail/{state['analysis']['category'].capitalize()}"
    if not state.get("dry_run"):
        call_tool("apply_label", {"message_id": state["email"]["id"], "label_name": label})
    log(state, "zugeordnet", label)

    event = state["analysis"].get("event")
    if event:
        log(state, "termin_vorgeschlagen", f"{event['title']}, {event['start']}")
    return {"label_applied": label}


def confirm_event(state: AgentState):
    """Hält an, bis jemand in der Oberfläche Ja oder Nein zum Termin sagt."""
    # Beim Fortsetzen läuft dieser Knoten von vorne, deshalb steht vor interrupt() nichts.
    approved = interrupt({"event": state["analysis"]["event"]})  # hier hält der Graph an
    action = "termin_bestaetigt" if approved else "termin_verworfen"
    log(state, action, state["analysis"]["event"]["title"], actor="nutzer")
    return {"event_approved": bool(approved)}


def create_event(state: AgentState):
    """Trägt den Termin in Google Kalender ein. Ohne Endzeit in der Mail: eine Stunde."""
    if state.get("dry_run"):
        log(state, "termin_eingetragen", "Testlauf, nichts in den Kalender geschrieben")
        return {"event_link": "(Testlauf, nichts eingetragen)"}

    event = state["analysis"]["event"]
    start = datetime.fromisoformat(event["start"])
    end = datetime.fromisoformat(event["end"]) if event.get("end") else start + timedelta(hours=1)
    created = call_tool("create_calendar_event", {
        "title": event["title"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": event.get("location"),
        "description": state["analysis"]["summary"],
    })
    log(state, "termin_eingetragen", created.get("link", ""))
    return {"event_link": created.get("link")}


# -----------------------------------------------------------------------------
# 4. Weichen (bedingte Kanten)
# -----------------------------------------------------------------------------
def route_after_label(state: AgentState):
    """Termin gefunden: weiter zu confirm_event. Sonst: fertig."""
    if state["analysis"].get("event"):
        return "confirm_event"
    return END


def route_after_confirm(state: AgentState):
    """Ja: weiter zu create_event. Nein: fertig."""
    if state.get("event_approved"):
        return "create_event"
    return END


# -----------------------------------------------------------------------------
# 5. Graph bauen
# -----------------------------------------------------------------------------
def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)
    builder.add_node("analyze", analyze)
    builder.add_node("apply_label", apply_label)
    builder.add_node("confirm_event", confirm_event)
    builder.add_node("create_event", create_event)

    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", "apply_label")
    builder.add_conditional_edges("apply_label", route_after_label, ["confirm_event", END])
    builder.add_conditional_edges("confirm_event", route_after_confirm, ["create_event", END])
    builder.add_edge("create_event", END)
    return builder.compile(checkpointer=checkpointer)


# Wie InMemorySaver im Notebook 08, nur dauerhaft in SQLite.
# check_same_thread=False: mehrere Mails werden gleichzeitig in eigenen Threads verarbeitet.
checkpointer = SqliteSaver(sqlite3.connect(store.DB_PATH, check_same_thread=False))
graph = build_graph(checkpointer)


# -----------------------------------------------------------------------------
# 6. Den Graphen benutzen (aufgerufen von agent/inbox.py und app/main.py)
#    Jede Mail hat ihren eigenen Verlauf (thread_id), Testmails mit Präfix "dry-".
# -----------------------------------------------------------------------------
def config_for(email_id, dry_run):
    prefix = "dry-" if dry_run else ""
    return {"configurable": {"thread_id": prefix + email_id}}


def status_of(config):
    """'awaiting_confirmation', wenn der Graph beim Termin wartet, sonst 'done'."""
    if graph.get_state(config).next:
        return "awaiting_confirmation"
    return "done"


def run_agent(email, dry_run=False):
    """Lässt eine Mail durch den Graphen laufen und speichert das Ergebnis."""
    config = config_for(email["id"], dry_run)
    try:
        graph.invoke({"email": email, "dry_run": dry_run}, config)
    except Exception as error:
        store.log("fehler", email["id"], email["subject"], str(error)[:300], "test" if dry_run else "gmail")
        raise
    store.save_analysis(email["id"], graph.get_state(config).values, status_of(config))


def resume_agent(email_id, approved, dry_run=False):
    """Setzt nach Ja/Nein zu einem Terminvorschlag fort (wie Command(resume=...) im Notebook 08)."""
    config = config_for(email_id, dry_run)
    try:
        graph.invoke(Command(resume=approved), config)
    except Exception as error:
        store.log("fehler", email_id, details=str(error)[:300], source="test" if dry_run else "gmail")
        raise
    store.save_decision(email_id, status_of(config), graph.get_state(config).values.get("event_link"))
