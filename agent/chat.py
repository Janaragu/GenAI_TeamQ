"""Chatfenster: Fragen zu den eigenen Mails stellen (wie Gemini in Gmail).

Ablauf pro Frage:
  1. Die neuesten Mails (mit KI-Zusammenfassung) kommen als Liste in den Prompt.
  2. Das LLM antwortet strukturiert (ChatAnswer in schemas.py).
  3. Will der Nutzer antworten ("Antworte Anna, dass ich komme"), nennt das LLM
     die Mail-ID. Dann schreibt agent/reply.py den Entwurf. Gesendet wird nie
     aus dem Chat, sondern erst in der Mail mit "Senden".

Guardrails (Schutzregeln):
  - Frage höchstens MAX_QUESTION_CHARS Zeichen (prüft app/main.py)
  - Prompt: nur Fragen zu den Mails, Mails sind Daten, keine Befehle daraus befolgen
  - on_topic=False: Der Code ersetzt die Antwort durch einen festen Satz
  - Eine Mail-ID vom LLM wird nur benutzt, wenn sie wirklich in der Liste stand
  - Der Chat kann nichts senden, löschen oder ändern, nur lesen und Entwürfe schreiben
  - Die Oberfläche zeigt Antworten als Text an, nie als HTML (kein Code in der Seite)
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from agent import llm, reply, store
from agent.prompts import CHAT_PROMPT
from schemas import ChatAnswer

MAX_MAILS = 40              # so viele neueste Mails sieht das LLM
MAX_SNIPPET_CHARS = 400     # Anfang des Mailtexts, falls noch keine Zusammenfassung da ist
MAX_HISTORY = 6             # so viele frühere Nachrichten gehen mit (Gedächtnis des Chats)
MAX_QUESTION_CHARS = 500
OFF_TOPIC = "Dazu kann ich nichts sagen. Ich beantworte nur Fragen zu deinen Mails."
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Zurich"))
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


# -----------------------------------------------------------------------------
# 1. Die Mails als Text für den Prompt, eine kurze Zeile pro Mail
# -----------------------------------------------------------------------------
def local_time(iso):
    """'2026-11-19T10:05:00+00:00' -> 'Mi 19.11.2026 11:05' (Ortszeit)."""
    if not iso:
        return "unbekannt"
    date = datetime.fromisoformat(iso)
    if date.tzinfo:
        date = date.astimezone(TIMEZONE)
    return f"{WEEKDAYS[date.weekday()][:2]} {date:%d.%m.%Y %H:%M}"


def mail_line(mail):
    """Eine Mail als Textblock: ID, Datum, Absender, Betreff, Kategorie, Inhalt."""
    content = mail["summary"] or (mail["body"] or "")[:MAX_SNIPPET_CHARS].replace("\n", " ")
    lines = [
        f"ID: {mail['id']}",
        f"Empfangen: {local_time(mail['received_at'])}",
        f"Von: {mail['sender']}",
        f"Betreff: {mail['subject']}",
        f"Kategorie: {mail['category'] or 'noch nicht analysiert'}",
        f"Inhalt: {content}",
    ]
    if mail["event"]:
        lines.append(f"Termin: {mail['event']['title']}, {mail['event']['start']}")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# 2. Eine Frage beantworten
#    history = frühere Nachrichten: [{"role": "user" | "assistant", "text": "..."}]
#    Rückgabe: {"answer": Text, "draft": None oder {mail_id, subject, body}}
# -----------------------------------------------------------------------------
def ask(question, history, source):
    mails = store.recent_emails(source, MAX_MAILS)
    now = datetime.now(TIMEZONE)
    system = CHAT_PROMPT.format(
        today=f"{WEEKDAYS[now.weekday()]}, {now:%d.%m.%Y %H:%M}",
        mails="\n\n".join(mail_line(mail) for mail in mails) or "(keine Mails)",
    )

    # Frühere Nachrichten mitschicken, damit Rückfragen wie "und die zweite?" funktionieren.
    messages = [SystemMessage(content=system)]
    for item in history[-MAX_HISTORY:]:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["text"]))
        else:
            messages.append(AIMessage(content=item["text"]))
    messages.append(HumanMessage(content=question))

    result = llm.get_llm().with_structured_output(ChatAnswer, method="json_schema").invoke(messages)

    # Guardrail: Fragen zu anderen Themen bekommen immer denselben festen Satz.
    if not result.on_topic:
        return {"answer": OFF_TOPIC, "draft": None}

    # Antwort gewünscht? Nur Mails aus der Liste zulassen, keine erfundenen IDs.
    by_id = {mail["id"]: mail for mail in mails}
    if result.reply_to_id in by_id and result.reply_instruction:
        mail = by_id[result.reply_to_id]
        draft = {
            "mail_id": mail["id"],
            "subject": mail["subject"],
            "body": reply.draft_reply(mail, result.reply_instruction),
        }
        # Fester Satz statt LLM-Text: Das LLM fragte sonst oft "Soll ich antworten?",
        # obwohl der Entwurf schon da ist.
        answer = f"Hier ist ein Entwurf für die Antwort an {mail['sender']}. Öffne die Mail, prüfe ihn und drücke dort Senden."
        return {"answer": answer, "draft": draft}

    return {"answer": result.answer, "draft": None}
