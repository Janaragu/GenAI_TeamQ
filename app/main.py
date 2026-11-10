"""Postfach-Oberfläche mit automatischer Zuordnung: python -m app.main"""

import html
import os
from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

import gradio as gr
from dotenv import load_dotenv

from agent import inbox, store
from agent.graph import resume_agent
from schemas import AgentStatus
from mcp_server.google_api import TOKEN_FILE

load_dotenv()

SYNC_SECONDS = 60
LOG_VIEW = "log"
MAILBOXES = [
    (store.INBOX, "Posteingang"),
    ("termin", "Termine"),
    ("aufgabe", "Aufgaben"),
    ("info", "Info"),
    ("newsletter", "Newsletter"),
    ("spam", "Spam"),
    (store.STATUS_FAILED, "Nicht zugeordnet"),
]
LOG_HEADERS = ["Zeit", "Quelle", "Wer", "Aktion", "Betreff", "Details"]
CHIP_TEXT = {
    "termin": "Termin",
    "aufgabe": "Aufgabe",
    "info": "Info",
    "newsletter": "Newsletter",
    "spam": "Spam",
}

CSS = """
.gradio-container { max-width: 100% !important; }
.topbar h1 { margin: 0; font-size: 22px; font-weight: 500; }
.nav-column { gap: 2px !important; }
.nav-column button:not(.primary) {
    justify-content: flex-start; text-align: left; border: 0; box-shadow: none;
    background: transparent; border-radius: 0 16px 16px 0; font-weight: 400;
}
.nav-column button:not(.primary):hover { background: var(--background-fill-secondary); }
.nav-column button.active:not(.primary) { background: rgba(66, 133, 244, 0.18); font-weight: 700; }
.mail-list { border: 1px solid var(--border-color-primary); border-radius: 8px; overflow: hidden; }
.mail-list, .mail-list .column, .mail-list > div { gap: 0 !important; }
.mail-list .block, .mail-list .html-container { min-height: 0 !important; padding: 0 !important; margin: 0 !important; }
.mail-row {
    display: grid; grid-template-columns: 190px 84px minmax(0, 1fr) 70px; gap: 12px;
    align-items: center; padding: 10px 14px; cursor: pointer;
    border-bottom: 1px solid var(--border-color-primary); font-size: 14px;
}
.mail-row:hover { background: var(--background-fill-secondary); }
.mail-row span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.mail-row .preview { color: var(--body-text-color-subdued); }
.mail-row .date { text-align: right; font-size: 12px; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; background: rgba(120, 120, 120, 0.18); }
.chip.termin { background: rgba(66, 133, 244, 0.22); }
.chip.aufgabe { background: rgba(251, 188, 4, 0.28); }
.chip.spam { background: rgba(234, 67, 53, 0.22); }
.chip.newsletter { background: rgba(52, 168, 83, 0.22); }
.empty { padding: 48px; text-align: center; color: var(--body-text-color-subdued); }
.detail h2 { margin: 0 0 8px; font-size: 20px; font-weight: 500; }
.detail .meta { color: var(--body-text-color-subdued); font-size: 13px; margin-bottom: 12px; }
.detail .box { padding: 10px 14px; border-radius: 8px; background: var(--background-fill-secondary); margin-bottom: 14px; }
.detail .body { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5; }
@media (max-width: 720px) {
    .mail-row { grid-template-columns: minmax(0, 1fr) 70px; }
    .mail-row .chip-cell { display: none; }
    .mail-row .preview { grid-column: 1 / -1; }
}
"""


def _esc(value: str | None) -> str:
    return html.escape(value or "")


def _local(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment.astimezone(ZoneInfo(os.getenv("TIMEZONE", "Europe/Zurich")))


def _short_date(value: str | None) -> str:
    moment = _local(value)
    if moment is None:
        return ""
    return f"{moment:%H:%M}" if moment.date() == datetime.now(moment.tzinfo).date() else f"{moment:%d.%m.%y}"


def _chip(mail: dict) -> str:
    category = mail["category"]
    text = CHIP_TEXT.get(category, "Nicht zugeordnet")
    return f'<span class="chip {category or ""}">{text}</span>'


def _row_html(mail: dict) -> str:
    return (
        '<div class="mail-row">'
        f"<span>{_esc(mail['sender'])}</span>"
        f'<span class="chip-cell">{_chip(mail)}</span>'
        f'<span class="preview"><b>{_esc(mail["subject"])}</b> – {_esc(mail["summary"])}</span>'
        f'<span class="date">{_short_date(mail["received_at"])}</span>'
        "</div>"
    )


def _event_box(mail: dict) -> str:
    event = mail["event"]
    if not event:
        return ""
    start = datetime.fromisoformat(event["start"])
    place = f", {_esc(event['location'])}" if event.get("location") else ""
    text = f"<b>Termin:</b> {_esc(event['title'])}, {start:%d.%m.%Y %H:%M}{place}"
    if mail["status"] == AgentStatus.AWAITING_CONFIRMATION.value:
        return f'<div class="box">{text}<br>Wartet auf deine Bestätigung.</div>'
    link = mail["event_link"]
    if not link:
        return f'<div class="box">{text}<br>Verworfen.</div>'
    if link.startswith("https://"):
        return f'<div class="box">{text}<br><a href="{_esc(link)}" target="_blank">Im Kalender öffnen</a></div>'
    return f'<div class="box">{text}<br>{_esc(link)}</div>'


def _detail_html(mail: dict) -> str:
    moment = _local(mail["received_at"])
    received = f"{moment:%d.%m.%Y %H:%M}" if moment else ""
    return (
        '<div class="detail">'
        f"<h2>{_esc(mail['subject'])}</h2>"
        f'<div class="meta">{_esc(mail["sender"])} · {received} · {_chip(mail)}</div>'
        f'<div class="box"><b>Zusammenfassung:</b> {_esc(mail["summary"])}</div>'
        f"{_event_box(mail)}"
        f'<div class="body">{_esc(mail["body"])}</div>'
        "</div>"
    )


def _log_rows() -> list[list[str]]:
    keys = ("source", "actor", "action", "subject", "details")
    return [
        [entry["timestamp"][:19].replace("T", " "), *(entry[key] or "" for key in keys)]
        for entry in store.list_log()
    ]


def _nav_updates(active: str, use_testset: bool) -> list:
    counts = store.mailbox_counts(inbox.source_name(use_testset))
    updates = []
    for key, name in MAILBOXES:
        count = counts.get(key, 0)
        classes = ["active"] if key == active else []
        updates.append(gr.update(value=f"{name}  ({count})" if count else name, elem_classes=classes))
    updates.append(gr.update(elem_classes=["active"] if active == LOG_VIEW else []))
    return updates


def build_app() -> gr.Blocks:
    with gr.Blocks(title="LocalMail AI") as demo:
        mailbox = gr.State(store.INBOX)
        selected = gr.State(None)
        search = gr.State("")
        version = gr.State(0)

        with gr.Row(elem_classes="topbar"):
            gr.HTML("<h1>LocalMail AI</h1>", scale=1)
            query = gr.Textbox(
                placeholder="In E-Mails suchen, mit Enter bestätigen",
                show_label=False,
                container=False,
                scale=4,
            )

        with gr.Row():
            with gr.Column(scale=1, min_width=210, elem_classes="nav-column"):
                fetch = gr.Button("Jetzt abrufen", variant="primary")
                nav_buttons = [gr.Button(name) for _, name in MAILBOXES]
                log_button = gr.Button("Protokoll")
                use_testset = gr.Checkbox(
                    value=not TOKEN_FILE.exists(),
                    label="Testmails statt Gmail",
                )
                status = gr.Markdown()

            with gr.Column(scale=5):
                with gr.Column(elem_classes="mail-list") as list_view:
                    @gr.render(inputs=[mailbox, search, use_testset, version])
                    def render_list(box, term, testset, _version):
                        if box == LOG_VIEW:
                            return
                        source = inbox.source_name(testset)
                        mails = store.list_emails(source, box, term)
                        if not mails:
                            gr.HTML('<div class="empty">Keine Mails in diesem Ordner.</div>')
                            return
                        for mail in mails:
                            row = gr.HTML(_row_html(mail), padding=False)
                            row.click(partial(open_mail, mail["id"]), None, open_outputs)

                with gr.Column(visible=False) as detail_view:
                    back = gr.Button("← Zurück", size="sm")
                    detail = gr.HTML()
                    with gr.Row(visible=False) as confirm_row:
                        approve = gr.Button("In Kalender eintragen", variant="primary")
                        reject = gr.Button("Verwerfen")

                with gr.Column(visible=False) as log_view:
                    gr.Markdown("## Protokoll")
                    download = gr.DownloadButton("Als Markdown herunterladen")
                    log_table = gr.Dataframe(
                        headers=LOG_HEADERS,
                        interactive=False,
                        wrap=True,
                        column_widths=["15%", "7%", "7%", "16%", "22%", "33%"],
                    )

        timer = gr.Timer(SYNC_SECONDS)
        all_nav = [*nav_buttons, log_button]
        open_outputs = [selected, list_view, detail_view, detail, confirm_row]

        def open_mail(email_id: str):
            mail = store.get_email(email_id)
            waiting = mail["status"] == AgentStatus.AWAITING_CONFIRMATION.value
            return (
                email_id,
                gr.update(visible=False),
                gr.update(visible=True),
                _detail_html(mail),
                gr.update(visible=waiting),
            )

        def show_mailbox(key: str, testset: bool):
            is_log = key == LOG_VIEW
            return (
                key,
                None,
                gr.update(visible=not is_log),
                gr.update(visible=False),
                gr.update(visible=is_log),
                gr.update(value=_log_rows()) if is_log else gr.update(),
                gr.update(value=store.export_markdown()) if is_log else gr.update(),
                *_nav_updates(key, testset),
            )

        show_outputs = [
            mailbox, selected, list_view, detail_view, log_view, log_table, download, *all_nav,
        ]
        for (key, _), button in zip(MAILBOXES, nav_buttons):
            button.click(partial(show_mailbox, key), use_testset, show_outputs)
        log_button.click(partial(show_mailbox, LOG_VIEW), use_testset, show_outputs)

        def run_sync(testset: bool, current: int, box: str):
            try:
                result = inbox.sync(testset)
            except Exception as error:
                return current, f"Abruf fehlgeschlagen: {error}", *_nav_updates(box, testset)
            if result.busy:
                return current, "Abruf läuft bereits.", *_nav_updates(box, testset)
            message = f"Zuletzt geprüft: {datetime.now():%H:%M}, {result.new} neu"
            if result.failed:
                message += f", {result.failed} fehlgeschlagen"
            changed = result.new or result.failed
            return current + 1 if changed else current, message, *_nav_updates(box, testset)

        sync_inputs = [use_testset, version, mailbox]
        sync_outputs = [version, status, *all_nav]
        demo.load(run_sync, sync_inputs, sync_outputs)
        fetch.click(run_sync, sync_inputs, sync_outputs)
        timer.tick(run_sync, sync_inputs, sync_outputs)

        def change_source(testset: bool, current: int):
            return (*show_mailbox(store.INBOX, testset), current + 1)

        use_testset.change(change_source, [use_testset, version], [*show_outputs, version]).then(
            run_sync, sync_inputs, sync_outputs
        )

        query.submit(lambda text: text.strip(), query, search)

        back.click(
            lambda: (None, gr.update(visible=True), gr.update(visible=False)),
            None,
            [selected, list_view, detail_view],
        )

        def decide(email_id: str | None, approved: bool, testset: bool, current: int, box: str):
            mail = store.get_email(email_id) if email_id else None
            if not mail or mail["status"] != AgentStatus.AWAITING_CONFIRMATION.value:
                raise gr.Error("Für diese Mail ist keine Entscheidung offen.")
            try:
                resume_agent(email_id, approved, dry_run=testset)
            except Exception as error:
                raise gr.Error(f"Das hat nicht geklappt: {error}")
            return (*open_mail(email_id), current + 1, *_nav_updates(box, testset))

        decide_inputs = [selected, use_testset, version, mailbox]
        decide_outputs = [*open_outputs, version, *all_nav]
        approve.click(partial(_call_with, decide, True), decide_inputs, decide_outputs)
        reject.click(partial(_call_with, decide, False), decide_inputs, decide_outputs)
    return demo


def _call_with(decide, approved, email_id, testset, current, box):
    return decide(email_id, approved, testset, current, box)


if __name__ == "__main__":
    build_app().launch(css=CSS)
