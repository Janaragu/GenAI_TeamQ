// =============================================================================
// Verhalten der Oberfläche im Browser.
// Holt Daten über die /api/... Adressen von app/main.py und baut daraus die
// Seite. Texte aus Mails werden immer mit textContent eingefügt, nie als HTML,
// damit eine Mail keinen fremden Code in die Seite schmuggeln kann.
// =============================================================================
"use strict";

// ----- 1. Ordner, Labels und Zustand der Seite -----
const NAV_MAIN = [
  { key: "inbox", name: "Posteingang", icon: "inbox" },
  { key: "spam", name: "Spam", icon: "report" },
  { key: "failed", name: "Nicht zugeordnet", icon: "help" },
  { key: "log", name: "Protokoll", icon: "history" },
];
const NAV_LABELS = [
  { key: "termin", name: "Termine", color: "#1a73e8" },
  { key: "aufgabe", name: "Aufgaben", color: "#f9ab00" },
  { key: "info", name: "Info", color: "#80868b" },
  { key: "newsletter", name: "Newsletter", color: "#188038" },
];
const CHIP_TEXT = {
  termin: "Termin", aufgabe: "Aufgabe", info: "Info", newsletter: "Newsletter", spam: "Spam",
};
const SYNC_INTERVAL_MS = 60 * 1000; // automatischer Abruf jede Minute

// Antwort-Vorschläge (Knöpfe) pro Kategorie. Der Knopftext ist zugleich die
// Anweisung an die KI. Newsletter und Spam beantwortet man nicht, also keine Knöpfe.
const REPLY_SUGGESTIONS = {
  termin: ["Termin annehmen", "Termin ablehnen", "Anderen Termin vorschlagen"],
  aufgabe: ["Zusagen, dass ich mich darum kümmere", "Rückfrage stellen", "Freundlich ablehnen"],
  info: ["Kurz bedanken"],
};

const state = {
  box: "inbox",        // gewählter Ordner
  search: "",          // aktueller Suchbegriff
  testset: false,      // true = Testmails statt Gmail
  openId: null,        // ID der geöffneten Mail
  calendarOpen: false, // Kalender rechts sichtbar?
  chatOpen: false,     // Chat rechts sichtbar?
  chat: [],            // Chatverlauf: [{ role: "user" | "assistant", text }], nur im Browser
  engine: null,        // Antwort von /api/engine
};

const $ = (selector) => document.querySelector(selector);

// ----- 2. Kleine Helfer -----

// Baut ein HTML-Element. Beispiel: el("span", { class: "chip", text: "Info" })
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  node.append(...children.filter(Boolean));
  return node;
}

const icon = (name, cls = "") => el("span", { class: `ms ${cls}`, text: name });

// Ruft die API auf. Hängt automatisch den Testmodus an und meldet Fehler.
async function api(path, options = {}) {
  const sep = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${sep}testset=${state.testset}`, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Fehler ${response.status}`);
  }
  return response.json();
}

let toastTimer;
function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), 5000);
}

// Datumsangaben im Stil von Gmail: heute "14:05", sonst "13. Nov.", ältere "13.11.24"
function listDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
  }
  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString("de-CH", { day: "numeric", month: "short" });
  }
  return date.toLocaleDateString("de-CH", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

function fullDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("de-CH", {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// "Anna Keller <anna@fhnw.ch>"  ->  { name: "Anna Keller", address: "anna@fhnw.ch" }
function parseSender(sender) {
  const match = (sender || "").match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
  if (match && match[1]) return { name: match[1], address: match[2] };
  return { name: sender || "(unbekannt)", address: match ? match[2] : "" };
}

// Gleicher Absender bekommt immer dieselbe Avatar-Farbe.
function avatarColor(text) {
  const colors = ["#1a73e8", "#d93025", "#188038", "#e37400", "#a142f4", "#007b83", "#c5221f"];
  let hash = 0;
  for (const ch of text) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return colors[hash % colors.length];
}

function chip(category) {
  const key = category || "failed";
  return el("span", { class: `chip ${key}`, text: CHIP_TEXT[key] || "Nicht zugeordnet" });
}

// Chip passend zum Stand der Mail: noch nicht analysiert, fehlgeschlagen oder Kategorie.
function mailChip(mail) {
  if (mail.status === "pending") return el("span", { class: "chip pending", text: "Nicht analysiert" });
  return chip(mail.status === "failed" ? null : mail.category);
}

function showView(name) {
  for (const view of ["list", "mail", "log"]) $(`#${view}-view`).hidden = view !== name;
}

// ----- 3. Linke Seitenleiste: Ordner mit Anzahl ungelesener Mails -----
function navItem(item, count, iconNode) {
  const classes = ["nav-item"];
  if (item.key === state.box) classes.push("active");
  if (count) classes.push("unread");
  return el("li", {},
    el("button", { class: classes.join(" "), title: item.name, onclick: () => selectBox(item.key) },
      iconNode,
      el("span", { class: "name", text: item.name }),
      el("span", { class: "count", text: count ? String(count) : "" }),
    ),
  );
}

async function refreshNav() {
  const status = await api("/api/status");
  const unread = status.unread || {};
  $("#nav-main").replaceChildren(
    ...NAV_MAIN.map((item) => navItem(item, item.key === "log" ? 0 : unread[item.key], icon(item.icon))),
  );
  $("#nav-labels").replaceChildren(
    ...NAV_LABELS.map((item) => {
      const labelIcon = icon("label", "label-icon");
      labelIcon.style.color = item.color;
      return navItem(item, unread[item.key], labelIcon);
    }),
  );
  return status;
}

function selectBox(key) {
  state.box = key;
  state.openId = null;
  if (key === "log") loadLog();
  else loadList();
  refreshNav();
}

// ----- 4. Mail-Liste -----
function mailRow(mail) {
  const sender = parseSender(mail.sender);
  const open = () => openMail(mail.id);
  return el("div",
    {
      class: mail.seen ? "row" : "row unread",
      role: "button",
      tabindex: "0",
      onclick: open,
      onkeydown: (event) => { if (event.key === "Enter") open(); },
    },
    el("span", { class: "sender", text: sender.name, title: mail.sender }),
    el("span", { class: "subject-cell" },
      state.box === "inbox" ? mailChip(mail) : null,
      el("span", { class: "subject", text: mail.subject || "(kein Betreff)" }),
      el("span", { class: "snippet", text: mail.summary ? ` – ${mail.summary}` : "" }),
    ),
    el("span", { class: "date", text: listDate(mail.received_at) }),
  );
}

async function loadList() {
  showView("list");
  const params = new URLSearchParams({ box: state.box, q: state.search });
  try {
    const mails = await api(`/api/mails?${params}`);
    $("#list-range").textContent = mails.length ? `1–${mails.length} von ${mails.length}` : "";
    $("#mail-list").replaceChildren(
      ...(mails.length
        ? mails.map(mailRow)
        : [el("div", { class: "empty", text: state.search ? "Keine Treffer." : "Keine Mails in diesem Ordner." })]),
    );
  } catch (error) {
    toast(error.message);
  }
}

// ----- 5. Geöffnete Mail mit KI-Zusammenfassung und Terminvorschlag -----
function eventCard(mail) {
  const event = mail.event;
  if (!event) return null;
  const start = new Date(event.start);
  const when = start.toLocaleString("de-CH", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
  const card = el("div", { class: "card event" },
    el("div", { class: "card-title" }, icon("event"), el("span", { text: event.title })),
    el("div", { class: "when", text: when + (event.location ? `, ${event.location}` : "") }),
  );

  // Überschneidungen mit bestehenden Terminen im Google Kalender
  if (mail.conflicts && mail.conflicts.length) {
    const names = mail.conflicts.map((c) => c.title).join(", ");
    card.append(el("div", { class: "warn", text: `Überschneidet sich mit: ${names}` }));
  }

  if (mail.status === "awaiting_confirmation") {
    const yes = el("button", { class: "btn filled", text: "In Kalender eintragen", onclick: () => decide(true) });
    const no = el("button", { class: "btn", text: "Verwerfen", onclick: () => decide(false) });
    card.append(el("div", { class: "actions" }, yes, no));
  } else if (mail.event_link && mail.event_link.startsWith("https://")) {
    card.append(el("div", { class: "actions" },
      el("a", { class: "link", href: mail.event_link, target: "_blank", rel: "noopener", text: "Im Google Kalender öffnen" })));
  } else if (mail.event_link) {
    card.append(el("div", { class: "actions", text: "Eingetragen (Testlauf, nicht im echten Kalender)." }));
  } else {
    card.append(el("div", { class: "actions", text: "Verworfen." }));
  }
  return card;
}

// Antwort-Bereich unter der Mail (wie "Antworten" in Gmail):
// Vorschlag-Knöpfe und eigene Anweisung lassen die KI einen Entwurf schreiben.
// Der Entwurf landet im Textfeld. Gesendet wird erst mit dem Knopf "Senden".
function replyCard(mail) {
  const text = el("textarea", { class: "reply-text", id: "reply-text", rows: "8", placeholder: "Antwort schreiben…" });
  const instruction = el("input", {
    class: "reply-instruction", type: "text", autocomplete: "off",
    placeholder: "Anweisung an die KI, z. B. Lehne freundlich und professionell ab",
  });
  const status = el("span", { class: "reply-status" });

  // Alle Knöpfe und Felder sperren, solange die KI schreibt oder gesendet wird.
  const setBusy = (busy, message = "") => {
    card.querySelectorAll("button, input, textarea").forEach((node) => (node.disabled = busy));
    status.textContent = message;
  };

  async function draft(prompt) {
    if (!prompt.trim()) return;
    setBusy(true, "KI schreibt einen Entwurf…");
    try {
      const data = await api(`/api/mails/${encodeURIComponent(mail.id)}/reply/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: prompt }),
      });
      text.value = data.body;  // ersetzt den bisherigen Text im Antwortfeld
      setBusy(false, "Entwurf bereit: prüfen, anpassen, dann senden.");
      text.focus();
    } catch (error) {
      setBusy(false);
      toast(error.message);
    }
  }

  async function send() {
    if (!text.value.trim()) return toast("Die Antwort ist leer.");
    setBusy(true, "Wird gesendet…");
    try {
      const result = await api(`/api/mails/${encodeURIComponent(mail.id)}/reply/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: text.value }),
      });
      text.value = "";
      setBusy(false, result.sent ? "Gesendet." : "Testlauf: nur protokolliert, nicht gesendet.");
      toast(result.sent ? "Antwort gesendet." : "Testlauf: Antwort nicht gesendet.");
    } catch (error) {
      setBusy(false);
      toast(error.message);
    }
  }

  const suggestions = (REPLY_SUGGESTIONS[mail.category] || []).map((label) =>
    el("button", { class: "suggestion", type: "button", text: label, onclick: () => draft(label) }));

  const card = el("div", { class: "card reply" },
    el("div", { class: "card-title" }, icon("reply"), el("span", { text: "Antworten" })),
    suggestions.length ? el("div", { class: "suggestions" }, icon("auto_awesome"), ...suggestions) : null,
    el("form", { class: "reply-ask", onsubmit: (event) => { event.preventDefault(); draft(instruction.value); } },
      instruction,
      el("button", { class: "btn", type: "submit" }, "Entwurf"),
    ),
    text,
    el("div", { class: "actions" },
      el("button", { class: "btn filled", type: "button", text: "Senden", onclick: send }),
      el("button", { class: "btn", type: "button", text: "Leeren", onclick: () => { text.value = ""; status.textContent = ""; } }),
      status,
    ),
  );
  return card;
}

function renderMail(mail) {
  const sender = parseSender(mail.sender);
  const avatar = el("div", { class: "avatar", text: (sender.name.trim()[0] || "?").toUpperCase() });
  avatar.style.background = avatarColor(sender.address || sender.name);
  // filter(Boolean): eventCard() liefert null ohne Termin, sonst stünde "null" im Text.
  $("#mail-article").replaceChildren(...[
    el("h1", {}, el("span", { text: mail.subject || "(kein Betreff)" }), mailChip(mail)),
    el("div", { class: "mail-head" },
      avatar,
      el("div", { class: "from" },
        el("b", { text: sender.name }),
        sender.address ? el("span", { class: "addr", text: `<${sender.address}>` }) : null,
      ),
      el("span", { class: "mail-date", text: fullDate(mail.received_at) }),
    ),
    el("div", { class: "card" },
      el("div", { class: "card-title" }, icon("auto_awesome"), el("span", { text: "KI-Zusammenfassung" })),
      el("div", {
        class: mail.status === "pending" ? "pending-note" : null,
        text: mail.status === "pending"
          ? "Noch nicht analysiert. Sobald die KI-Engine bereit ist, wird die Mail beim nächsten Abruf einsortiert."
          : mail.summary || "",
      }),
    ),
    eventCard(mail),
    el("div", { class: "body", text: mail.body || "" }),
    replyCard(mail),
  ].filter(Boolean));
}

async function openMail(id) {
  state.openId = id;
  try {
    const mail = await api(`/api/mails/${encodeURIComponent(id)}`);
    renderMail(mail);
    showView("mail");
    refreshNav();
  } catch (error) {
    toast(error.message);
  }
}

async function decide(approved) {
  document.querySelectorAll(".card.event .btn").forEach((button) => (button.disabled = true));
  try {
    const mail = await api(`/api/mails/${encodeURIComponent(state.openId)}/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    renderMail(mail);
    toast(approved ? "Termin eingetragen." : "Termin verworfen.");
    if (state.calendarOpen) loadCalendar();
  } catch (error) {
    toast(error.message);
    document.querySelectorAll(".card.event .btn").forEach((button) => (button.disabled = false));
  }
}

// ----- 6. Protokoll -----
async function loadLog() {
  showView("log");
  try {
    const entries = await api("/api/log");
    $("#log-body").replaceChildren(
      ...entries.map((entry) => el("tr", {},
        el("td", { text: entry.timestamp.slice(0, 19).replace("T", " ") }),
        el("td", { text: entry.source }),
        el("td", { text: entry.actor }),
        el("td", { text: entry.action }),
        el("td", { text: entry.subject || "" }),
        el("td", { text: entry.details || "" }),
      )),
    );
  } catch (error) {
    toast(error.message);
  }
}

// ----- 7. Google Kalender rechts: Termine der nächsten 14 Tage, nach Tagen -----
function dayLabel(date) {
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (date.toDateString() === today.toDateString()) return "Heute";
  if (date.toDateString() === tomorrow.toDateString()) return "Morgen";
  return date.toLocaleDateString("de-CH", { weekday: "long", day: "numeric", month: "long" });
}

// Ganztägige Termine haben nur ein Datum ("2026-11-14"); als Ortszeit lesen.
const eventDate = (event) => (event.all_day ? new Date(`${event.start}T00:00:00`) : new Date(event.start));

async function loadCalendar() {
  const list = $("#calendar-list");
  list.replaceChildren(el("p", { class: "panel-sub", text: "Lädt…" }));
  try {
    const data = await api("/api/calendar");
    $("#calendar-sub").textContent = data.testmode
      ? "Testmodus: nur im Test bestätigte Termine, der echte Kalender wird nicht gelesen."
      : "Nächste 14 Tage aus deinem Google Kalender";
    if (!data.events.length) {
      list.replaceChildren(el("p", { class: "panel-sub", text: "Keine Termine." }));
      return;
    }
    const nodes = [];
    let lastDay = "";
    for (const event of data.events) {
      const date = eventDate(event);
      const label = dayLabel(date);
      if (label !== lastDay) {
        nodes.push(el("div", { class: label === "Heute" ? "day today" : "day", text: label }));
        lastDay = label;
      }
      const time = event.all_day
        ? "Ganztägig"
        : date.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
      const tag = event.link && event.link.startsWith("https://") ? "a" : "div";
      nodes.push(el(tag,
        { class: "event-item", href: tag === "a" ? event.link : null, target: tag === "a" ? "_blank" : null, rel: tag === "a" ? "noopener" : null },
        el("div", { class: "t", text: event.title }),
        el("div", { class: "s", text: time + (event.location ? ` · ${event.location}` : "") }),
      ));
    }
    list.replaceChildren(...nodes);
  } catch (error) {
    list.replaceChildren(el("p", { class: "panel-sub", text: error.message }));
  }
}

function toggleCalendar(open) {
  if (open && state.chatOpen) toggleChat(false);  // rechts ist nur Platz für ein Fenster
  state.calendarOpen = open;
  $("#calendar-panel").hidden = !open;
  $("#calendar-btn").classList.toggle("active", open);
  if (open) loadCalendar();
}

// ----- 7b. Chat mit der KI über die eigenen Mails (rechts, wie Gemini in Gmail) -----
// Beispielfragen, die vor der ersten Frage als Knöpfe erscheinen.
const CHAT_EXAMPLES = [
  "Was sind meine To-dos heute?",
  "Welche Mails habe ich in den letzten 5 Tagen bekommen?",
  "Gibt es Termine, die ich noch bestätigen muss?",
];

// Eine Nachricht im Verlauf. Text immer als textContent, nie als HTML.
function chatBubble(role, text, ...extra) {
  return el("div", { class: `bubble ${role}` }, el("div", { text }), ...extra);
}

// Entwurf aus dem Chat: Knopf öffnet die Mail und füllt das Antwortfeld.
// Gesendet wird erst dort mit "Senden".
function draftBox(draft) {
  async function open() {
    await openMail(draft.mail_id);
    const text = $("#reply-text");
    if (!text) return;
    text.value = draft.body;
    text.scrollIntoView({ behavior: "smooth", block: "center" });
    text.focus();
  }
  return el("div", { class: "chat-draft" },
    el("div", { class: "chat-draft-title", text: `Entwurf: Re: ${draft.subject}` }),
    el("div", { class: "chat-draft-body", text: draft.body }),
    el("button", { class: "btn small-primary", type: "button", text: "In Mail öffnen", onclick: open }),
  );
}

function renderChat() {
  const log = $("#chat-log");
  if (!state.chat.length) {
    log.replaceChildren(
      el("p", { class: "panel-sub", text: "Frag mich etwas zu deinen Mails. Ich kann auch Antworten entwerfen, z. B. „Antworte Anna, dass ich komme“." }),
      ...CHAT_EXAMPLES.map((example) =>
        el("button", { class: "suggestion", type: "button", text: example, onclick: () => askChat(example) })),
    );
    return;
  }
  log.replaceChildren(...state.chat.map((m) => chatBubble(m.role, m.text, m.draft ? draftBox(m.draft) : null)));
  log.scrollTop = log.scrollHeight;  // zur neuesten Nachricht
}

async function askChat(question) {
  question = question.trim();
  if (!question) return;
  const history = state.chat.map((m) => ({ role: m.role, text: m.text }));  // ohne Entwürfe
  state.chat.push({ role: "user", text: question });
  renderChat();
  $("#chat-log").append(el("div", { class: "bubble assistant pending-note", text: "Denkt nach…" }));
  $("#chat-input").value = "";
  $("#chat-input").disabled = true;
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    state.chat.push({ role: "assistant", text: data.answer, draft: data.draft });
  } catch (error) {
    state.chat.push({ role: "assistant", text: `Fehler: ${error.message}` });
  }
  $("#chat-input").disabled = false;
  $("#chat-input").focus();
  renderChat();
}

function toggleChat(open) {
  if (open && state.calendarOpen) toggleCalendar(false);  // rechts ist nur Platz für ein Fenster
  state.chatOpen = open;
  $("#chat-panel").hidden = !open;
  $("#chat-btn").classList.toggle("active", open);
  if (open) {
    renderChat();
    $("#chat-input").focus();
  }
}

// ----- 8. Automatischer Abruf neuer Mails -----
async function sync() {
  const button = $("#sync-btn");
  if (button.classList.contains("busy")) return;
  button.classList.add("busy");
  try {
    const result = await api("/api/sync", { method: "POST" });
    const time = new Date().toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
    $("#sync-status").textContent = result.skipped
      ? `Abgerufen ${time}. Analyse pausiert, KI-Engine nicht bereit` +
        (result.pending ? ` (${result.pending} warten)` : "")
      : `Zuletzt geprüft: ${time}` + (result.pending ? `, ${result.pending} warten auf Analyse` : "");
    loadEngine();
    if (result.new || result.failed) {
      let message = `${result.new} Mail${result.new === 1 ? "" : "s"} analysiert und einsortiert`;
      if (result.failed) message += `, ${result.failed} fehlgeschlagen`;
      toast(message);
    } else if (result.fetched) {
      toast(`${result.fetched} neue Mail${result.fetched === 1 ? "" : "s"} abgerufen` +
        (result.skipped ? ", Analyse folgt, sobald die KI-Engine bereit ist" : ""));
    }
    if ((result.new || result.failed || result.fetched) && !$("#list-view").hidden) loadList();
    await refreshNav();
  } catch (error) {
    $("#sync-status").textContent = "Abruf fehlgeschlagen";
    toast(error.message);
  } finally {
    button.classList.remove("busy");
  }
}

// ----- 8b. Alles zurücksetzen (z. B. vor einer Demo) -----
// Löscht Mails, Protokoll und Chat in LocalMail und holt danach alles neu.
// Gmail und Google Kalender bleiben, wie sie sind.
async function resetAll() {
  $("#settings-menu").hidden = true;
  const ok = confirm(
    "Alles zurücksetzen?\n\n" +
    "Gelöscht werden in LocalMail: alle Mails, Analysen, Terminvorschläge, das Protokoll und der Chat.\n" +
    "Danach werden die Mails neu abgerufen und neu analysiert.\n\n" +
    "Gmail und Google Kalender werden nicht verändert.",
  );
  if (!ok) return;
  try {
    await api("/api/reset", { method: "POST" });
  } catch (error) {
    return toast(error.message);
  }
  state.chat = [];
  if (state.chatOpen) renderChat();
  selectBox("inbox");
  toast("Zurückgesetzt. Mails werden neu abgerufen…");
  sync();
}

// ----- 9. Testmodus umschalten (wird im Browser gemerkt) -----
function applyMode() {
  $("#testset-toggle").checked = state.testset;
  $("#mode-badge").hidden = !state.testset;
  try { localStorage.setItem("localmail-testset", state.testset ? "1" : "0"); } catch (e) { /* egal */ }
}

// ----- 9b. KI-Engine: lokal (Ollama, LM Studio) oder Cloud-API -----
// Der API-Key wird nur beim Übernehmen an den eigenen Server geschickt und nie
// zurückgeliefert. Er landet nicht im Browser-Speicher.
const engineDraft = { mode: "local", provider: null };

function renderEngineChip(info) {
  const chipNode = $("#engine-chip");
  chipNode.classList.toggle("error", !info.ready);
  $("#engine-chip-icon").textContent = info.is_local ? "computer" : "cloud";
  $("#engine-chip-text").textContent = info.ready
    ? `${info.name.replace(" (lokal)", "")} · ${info.model}`
    : "Engine nicht bereit";
  chipNode.title = info.ready
    ? `KI-Engine: ${info.name}, Modell ${info.model}. Klicken zum Ändern.`
    : `KI-Engine nicht bereit: ${info.problem}`;
  $("#engine-alert").hidden = info.ready;
  $("#engine-alert-text").textContent = `KI-Engine nicht bereit (${info.name}): ${info.problem}`;
}

async function loadEngine() {
  try {
    state.engine = await api("/api/engine");
    renderEngineChip(state.engine);
  } catch (error) {
    toast(error.message);
  }
  return state.engine;
}

function setEngineMode(mode) {
  engineDraft.mode = mode;
  document.querySelectorAll(".segmented button").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#engine-local").hidden = mode !== "local";
  $("#engine-cloud").hidden = mode !== "cloud";
  $("#engine-error").hidden = true;
}

function renderServers() {
  const info = state.engine;
  const servers = Object.entries(info.local);
  if (!engineDraft.provider || !info.local[engineDraft.provider]) {
    const running = servers.find(([, server]) => server.running);
    engineDraft.provider = info.is_local ? info.provider : (running ? running[0] : servers[0][0]);
  }
  $("#server-list").replaceChildren(...servers.map(([key, server]) => {
    const classes = ["server"];
    if (server.running) classes.push("running");
    if (key === engineDraft.provider) classes.push("selected");
    const count = server.models.length;
    return el("button",
      {
        type: "button",
        class: classes.join(" "),
        disabled: !server.running,
        "aria-pressed": String(key === engineDraft.provider),
        onclick: () => { engineDraft.provider = key; renderServers(); },
      },
      icon(server.running ? "check_circle" : "radio_button_unchecked"),
      el("span", { class: "t", text: server.name.replace(" (lokal)", "") }),
      el("span", { class: "badge", text: server.running ? "läuft" : "nicht gefunden" }),
      el("span", {
        class: "s",
        text: server.running ? `${server.url} · ${count} Modell${count === 1 ? "" : "e"}` : `${server.url} antwortet nicht`,
      }),
    );
  }));

  const server = info.local[engineDraft.provider];
  const select = $("#local-model");
  const models = server.running ? server.models : [];
  select.replaceChildren(...models.map((name) => el("option", { value: name, text: name })));
  select.disabled = !models.length;
  if (!models.length) {
    select.replaceChildren(el("option", { text: "Kein lokaler Server gefunden. Ollama oder LM Studio starten." }));
  }
  const preferred = [info.provider === engineDraft.provider ? info.model : null, server.default_model]
    .find((name) => name && models.includes(name));
  if (preferred) select.value = preferred;
}

async function openEngineDialog() {
  $("#settings-menu").hidden = true;
  const info = await loadEngine();
  if (!info) return;
  engineDraft.provider = null;
  setEngineMode(info.is_local ? "local" : "cloud");
  renderServers();
  $("#cloud-url").value = info.cloud.base_url;
  $("#cloud-model").value = info.cloud.model;
  $("#cloud-key").value = "";
  $("#cloud-key").placeholder = info.cloud.has_key
    ? "Key ist gesetzt (wird nicht angezeigt). Leer lassen, um ihn zu behalten."
    : "API-Key eingeben";
  $("#test-result").hidden = true;
  $("#engine-dialog").showModal();
}

function engineChoice() {
  if (engineDraft.mode === "local") {
    return { provider: engineDraft.provider, model: $("#local-model").disabled ? "" : $("#local-model").value };
  }
  return {
    provider: "cloud",
    base_url: $("#cloud-url").value.trim(),
    model: $("#cloud-model").value.trim(),
    api_key: $("#cloud-key").value.trim(),
  };
}

async function postEngine(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Fehler ${response.status}`);
  return data;
}

async function rescanServers() {
  await loadEngine();
  renderServers();
}

async function testEngine() {
  const box = $("#test-result");
  box.hidden = false;
  box.className = "test-result";
  box.textContent = "Teste…";
  try {
    const result = await postEngine("/api/engine/test", engineChoice());
    box.classList.toggle("error", !result.ok);
    box.textContent = result.message;
  } catch (error) {
    box.classList.add("error");
    box.textContent = error.message;
  }
}

async function applyEngine() {
  const button = $("#engine-apply");
  button.disabled = true;
  try {
    const info = await postEngine("/api/engine", engineChoice());
    state.engine = info;
    renderEngineChip(info);
    $("#cloud-key").value = "";
    if (info.ready) {
      $("#engine-dialog").close();
      toast(`KI-Engine: ${info.name}, ${info.model}`);
      sync();
    } else {
      const error = $("#engine-error");
      error.hidden = false;
      error.textContent = `Gespeichert, aber nicht bereit: ${info.problem}`;
    }
  } catch (error) {
    const box = $("#engine-error");
    box.hidden = false;
    box.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function bindEngine() {
  $("#engine-chip").addEventListener("click", openEngineDialog);
  $("#engine-menu-btn").addEventListener("click", openEngineDialog);
  $("#engine-alert-btn").addEventListener("click", openEngineDialog);
  $("#engine-close").addEventListener("click", () => $("#engine-dialog").close());
  $("#engine-cancel").addEventListener("click", () => $("#engine-dialog").close());
  $("#engine-apply").addEventListener("click", applyEngine);
  $("#rescan-btn").addEventListener("click", rescanServers);
  $("#test-btn").addEventListener("click", testEngine);
  document.querySelectorAll(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      setEngineMode(button.dataset.mode);
      if (button.dataset.mode === "local") rescanServers();
    });
  });
  // Key nicht im Formular stehen lassen, wenn der Dialog ohne Übernehmen schliesst.
  $("#engine-dialog").addEventListener("close", () => ($("#cloud-key").value = ""));
}

// ----- 10. Start: Knöpfe verbinden, Modus wählen, ersten Abruf starten -----
async function init() {
  // Hauptmenü-Knopf klappt die linke Leiste auf Symbole zusammen (wie in Gmail).
  $("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("collapsed"));
  bindEngine();
  $("#sync-btn").addEventListener("click", sync);
  $("#refresh-btn").addEventListener("click", sync);
  $("#back-btn").addEventListener("click", () => { state.openId = null; loadList(); });
  $("#calendar-btn").addEventListener("click", () => toggleCalendar(!state.calendarOpen));
  $("#calendar-close").addEventListener("click", () => toggleCalendar(false));
  $("#chat-btn").addEventListener("click", () => toggleChat(!state.chatOpen));
  $("#chat-close").addEventListener("click", () => toggleChat(false));
  $("#chat-form").addEventListener("submit", (event) => { event.preventDefault(); askChat($("#chat-input").value); });
  // Hell/Dunkel umschalten. Der Startwert steht schon (Skript im <head> von index.html).
  const showTheme = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    $("#theme-icon").textContent = dark ? "light_mode" : "dark_mode";
    $("#theme-btn").title = dark ? "Hellmodus" : "Dunkelmodus";
    $("#theme-btn").setAttribute("aria-checked", String(dark));
  };
  $("#theme-btn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("localmail-theme", next); } catch (e) { /* egal */ }
    showTheme();
  });
  showTheme();
  $("#settings-btn").addEventListener("click", () => ($("#settings-menu").hidden = !$("#settings-menu").hidden));
  $("#reset-btn").addEventListener("click", resetAll);
  $("#testset-toggle").addEventListener("change", (event) => {
    state.testset = event.target.checked;
    applyMode();
    selectBox("inbox");
    if (state.calendarOpen) loadCalendar();
    sync();
  });
  $("#search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    state.search = $("#search-input").value.trim();
    $("#search-clear").hidden = !state.search;
    if (state.box === "log") state.box = "inbox";
    loadList();
    refreshNav();
  });
  $("#search-clear").addEventListener("click", () => {
    $("#search-input").value = "";
    state.search = "";
    $("#search-clear").hidden = true;
    loadList();
  });

  // Ohne Google-Anmeldung startet die Seite im Testmodus.
  const status = await api("/api/status");
  let saved = null;
  try { saved = localStorage.getItem("localmail-testset"); } catch (e) { /* egal */ }
  state.testset = !status.gmail_connected || saved === "1";
  $("#settings-hint").textContent = status.gmail_connected
    ? "Gmail ist verbunden. Im Testmodus wird nichts in Gmail oder den Kalender geschrieben."
    : "Gmail ist nicht verbunden (token.json fehlt). Anmelden mit: python -m mcp_server.auth";
  $("#testset-toggle").disabled = !status.gmail_connected;
  applyMode();

  selectBox("inbox");
  const engine = await loadEngine();
  if (engine && !engine.ready) openEngineDialog();
  sync();
  setInterval(sync, SYNC_INTERVAL_MS);
}

init();
