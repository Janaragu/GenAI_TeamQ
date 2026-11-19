"""Antworten auf Mails: Entwurf vom LLM, Senden erst auf Knopfdruck.

Ablauf in der Oberfläche:
  1. Nutzer öffnet eine Mail und drückt einen Vorschlag ("Termin annehmen")
     oder tippt eine eigene Anweisung ein ("Lehne freundlich ab").
  2. draft_reply() lässt das LLM daraus einen Antworttext schreiben.
  3. Der Text landet im Antwortfeld. Der Nutzer kann ihn ändern.
  4. Erst "Senden" ruft send_reply() auf. Das LLM sendet nie selbst.

Bewusst kein Teil des Graphen (agent/graph.py): Der Graph läuft automatisch für
jede neue Mail, eine Antwort schreibt man nur, wenn man eine Mail offen hat.
"""

from langchain.messages import HumanMessage, SystemMessage

from agent import llm, store
from agent.graph import MAX_BODY_CHARS
from agent.prompts import REPLY_PROMPT, REPLY_TEMPLATE
from agent.tools import call_tool


def draft_reply(email, instruction):
    """Gibt einen Antworttext zurück (nur Text, ohne Betreff)."""
    prompt = REPLY_TEMPLATE.format(
        instruction=instruction,
        sender=email["sender"],
        subject=email["subject"],
        body=email["body"][:MAX_BODY_CHARS],
    )
    # Normaler Aufruf ohne Schema: Wir wollen nur Text zurück.
    answer = llm.get_llm().invoke([SystemMessage(content=REPLY_PROMPT), HumanMessage(content=prompt)])
    return answer.content.strip()


def send_reply(email, body):
    """Sendet die Antwort über den MCP-Server. Im Testmodus wird nichts gesendet."""
    if email["source"] == "test":
        store.log("antwort_gesendet", email["id"], email["subject"],
                  "Testlauf, nichts gesendet", source="test", actor="nutzer")
        return {"sent": False}

    call_tool("send_reply", {"message_id": email["id"], "body": body})
    store.log("antwort_gesendet", email["id"], email["subject"],
              f"an {email['sender']}", source="gmail", actor="nutzer")
    return {"sent": True}
