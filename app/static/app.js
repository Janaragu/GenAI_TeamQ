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

const state = {
  box: "inbox",        // gewählter Ordner
  search: "",          // aktueller Suchbegriff
  testset: false,      // true = Testmails statt Gmail
  openId: null,        // ID der geöffneten Mail
  calendarOpen: false, // Kalender rechts sichtbar?
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
  $("#sidebar").classList.remove("open");
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
      state.box === "inbox" ? chip(mail.status === "failed" ? null : mail.category) : null,
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

function renderMail(mail) {
  const sender = parseSender(mail.sender);
  const avatar = el("div", { class: "avatar", text: (sender.name.trim()[0] || "?").toUpperCase() });
  avatar.style.background = avatarColor(sender.address || sender.name);
  $("#mail-article").replaceChildren(
    el("h1", {}, el("span", { text: mail.subject || "(kein Betreff)" }), chip(mail.status === "failed" ? null : mail.category)),
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
      el("div", { text: mail.summary || "" }),
    ),
    eventCard(mail),
    el("div", { class: "body", text: mail.body || "" }),
  );
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
  state.calendarOpen = open;
  $("#calendar-panel").hidden = !open;
  $("#calendar-btn").classList.toggle("active", open);
  if (open) loadCalendar();
}

// ----- 8. Automatischer Abruf neuer Mails -----
async function sync() {
  const button = $("#sync-btn");
  if (button.classList.contains("busy")) return;
  button.classList.add("busy");
  try {
    const result = await api("/api/sync", { method: "POST" });
    const time = new Date().toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
    $("#sync-status").textContent = `Zuletzt geprüft: ${time}`;
    if (result.new || result.failed) {
      let message = `${result.new} neue Mail${result.new === 1 ? "" : "s"} einsortiert`;
      if (result.failed) message += `, ${result.failed} fehlgeschlagen`;
      toast(message);
      if (!$("#list-view").hidden) loadList();
    }
    await refreshNav();
  } catch (error) {
    $("#sync-status").textContent = "Abruf fehlgeschlagen";
    toast(error.message);
  } finally {
    button.classList.remove("busy");
  }
}

// ----- 9. Testmodus umschalten (wird im Browser gemerkt) -----
function applyMode() {
  $("#testset-toggle").checked = state.testset;
  $("#mode-badge").hidden = !state.testset;
  try { localStorage.setItem("localmail-testset", state.testset ? "1" : "0"); } catch (e) { /* egal */ }
}

// ----- 10. Start: Knöpfe verbinden, Modus wählen, ersten Abruf starten -----
async function init() {
  $("#menu-btn").addEventListener("click", () => {
    if (window.matchMedia("(max-width: 860px)").matches) $("#sidebar").classList.toggle("open");
    else $("#sidebar").classList.toggle("collapsed");
  });
  $("#sync-btn").addEventListener("click", sync);
  $("#refresh-btn").addEventListener("click", sync);
  $("#back-btn").addEventListener("click", () => { state.openId = null; loadList(); });
  $("#calendar-btn").addEventListener("click", () => toggleCalendar(!state.calendarOpen));
  $("#calendar-close").addEventListener("click", () => toggleCalendar(false));
  $("#settings-btn").addEventListener("click", () => ($("#settings-menu").hidden = !$("#settings-menu").hidden));
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
  sync();
  setInterval(sync, SYNC_INTERVAL_MS);
}

init();
