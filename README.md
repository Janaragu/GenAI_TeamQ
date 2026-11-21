# LocalMail AI

**Ein KI-Postfach, bei dem die Mails auf dem eigenen Rechner bleiben können.**

LocalMail AI holt Mails aus Gmail, sortiert sie automatisch in Kategorien, fasst sie zusammen, setzt Labels, schlägt Antworten vor, erkennt Termine und beantwortet Fragen zu den eigenen Mails in einem Chat. Die KI dahinter kann ein lokales Modell sein (Ollama oder LM Studio). Dann verlassen die Mail-Inhalte den Rechner nicht.

Gruppenarbeit im Modul Generative KI, FHNW. Abschlusspräsentation am 23.11.2026.

<!-- TODO Team: Namen und Rollen eintragen -->
| Person | Schwerpunkt |
| --- | --- |
| _Name_ | Lokale Modelle: Ollama/LM Studio als Engine, Benchmark |
| _Name_ | Testmails und Evaluation mit der Cloud-API |
| _Name_ | _…_ |
| _Name_ | _…_ |

---

## 1. Problemstellung

KI-Funktionen in Mailprogrammen sind praktisch: Zusammenfassungen, automatische Sortierung, Antwortvorschläge, ein Assistent, der die eigenen Mails kennt. Dafür werden die Mails aber normalerweise an die API eines grossen Anbieters geschickt und dort ausgewertet. Was mit den Daten danach passiert, etwa ob sie zum Verbessern von Modellen genutzt werden, liegt nicht mehr in der eigenen Hand.

Unsere Frage war: **Kann man ein Postfach bauen, das die wichtigsten KI-Funktionen bietet, ohne dass die Mails den eigenen Rechner verlassen müssen?**

Die Funktionen, die wir haben wollten:

- automatische Kategorisierung und Labeling
- Zusammenfassungen pro Mail
- Antwortvorschläge
- ein Chatbot, der die eigenen Mails als Kontext nutzt
- Termine aus Mails erkennen und in den Kalender eintragen

## 2. Lösungsansatz

Ein Agent mit **austauschbarer KI-Engine**. Alle drei Varianten sprechen dieselbe OpenAI-kompatible Schnittstelle, deshalb läuft derselbe Code mit jeder davon:

| Engine | Wo läuft das Modell? | Verlassen die Mails den Rechner? |
| --- | --- | --- |
| **Ollama** | lokal | nein |
| **LM Studio** | lokal | nein |
| **Cloud-API** (z. B. FHNW-Proxy) | beim Anbieter | ja |

Die Engine lässt sich im Dashboard umschalten, ohne Neustart. So können wir lokal und Cloud direkt miteinander vergleichen.

**Wichtig:** Der Mail-Abruf selbst läuft über die Gmail-API. Die Mails liegen also weiterhin bei Google. «Lokal» bezieht sich auf die KI-Auswertung: Mit Ollama oder LM Studio sieht kein KI-Anbieter die Mail-Inhalte.

## 3. Vorgehen

### Schritt 1: Mail-Anbindung finden

Ein Postfach braucht eine Verbindung zum Mail-Anbieter. Wir haben zuerst Anbieter wie Proton über IMAP versucht (IMAP ist das Standardprotokoll, über das Programme Mails von einem Server abrufen). Das hat bei uns nicht zuverlässig funktioniert. <!-- TODO Team: kurz ergänzen, woran es scheiterte -->

Funktioniert hat es mit **Gmail**: Ein Teammitglied hat ein Gmail-Testkonto angelegt. In der Google Cloud Console haben wir ein Projekt mit OAuth-Zugang («Desktop-App») eingerichtet. Die App greift über die **Gmail-API** und die **Google-Calendar-API** zu (Berechtigungen `gmail.modify` und `calendar.events`, also lesen, labeln und antworten, aber nicht löschen).

### Schritt 2: Agent und MCP-Server

- Ein eigener **MCP-Server** ([mcp_server/server.py](mcp_server/server.py)) stellt die Werkzeuge bereit: Mails auflisten und lesen, Label setzen, Antwort senden, Termine lesen und eintragen.
- Der **Agent** ist ein LangGraph-Graph ([agent/graph.py](agent/graph.py)). Pro Mail:

  ```
  START -> analyze -> apply_label -> (Termin gefunden?) -> confirm_event -> (Ja?) -> create_event -> END
  ```

  `analyze` lässt das LLM ein festes Schema ausfüllen ([schemas.py](schemas.py)): Kategorie, Zusammenfassung in höchstens zwei Sätzen, eventuell ein Termin. Bei einem Termin hält der Graph an (`interrupt`) und wartet auf Bestätigung. Ohne Ja wird nichts in den Kalender eingetragen.
- Fünf Kategorien, jede mit eigenem Gmail-Label: `termin`, `aufgabe`, `info`, `newsletter`, `spam`.

### Schritt 3: Oberfläche

Ein Postfach im Gmail-Stil, gebaut mit FastAPI und einer HTML/JS-Seite ([app/](app/)), entwickelt mit Unterstützung von Claude (Claude Code). Funktionen:

- Posteingang mit Ordnern pro Kategorie, Abruf jede Minute, solange die Seite offen ist
- Zusammenfassung und Terminvorschlag pro Mail, Warnung bei Überschneidungen im Kalender
- **Antworten:** Die KI schreibt einen Entwurf, gesendet wird erst auf Knopfdruck
- **Chat:** Fragen zu den eigenen Mails, mit Schutzregeln (siehe unten)
- Protokoll aller Aktionen, Dunkelmodus, «Alles zurücksetzen» für Demos
- Engine-Dialog: findet laufende Ollama- und LM-Studio-Server automatisch und zeigt deren Modelle

### Schritt 4: Testmails und Evaluation

- **Testset:** 22 selbst geschriebene Mails mit der richtigen Kategorie ([eval/data/testmails.json](eval/data/testmails.json)): 6 Termin, 5 Aufgabe, 4 Info, 4 Spam, 3 Newsletter.
- Verglichen werden die KI-Engines: Cloud-API gegen lokale Modelle, alle mit demselben Agenten und denselben Prompts.
- [eval/metrics.py](eval/metrics.py) misst Accuracy und Macro-F1 mit der eingestellten Engine. [eval/benchmark.py](eval/benchmark.py) misst zusätzlich die Zeit pro Mail für lokale Modelle.

### Schritt 5: Lokale Modelle

Ziel: dieselbe Analyse mit einem Modell auf dem eigenen Rechner, schnell genug für den Alltag.

- Ollama und LM Studio als Engine eingebunden ([agent/llm.py](agent/llm.py)).
- Wichtigste Erkenntnis: Mit eingeschaltetem «Denkmodus» brauchte `qwen3.5:4b` rund **133 s pro Mail**. Mit `reasoning_effort="none"` waren es rund **3 s** bei gleicher Trefferquote. Details: [docs/roadmap-ollama.md](docs/roadmap-ollama.md).

## 4. Ergebnisse

### Lokales Modell: Qwen 3.5 4B über Ollama

Gemessen am 19.11.2026 auf einem MacBook mit Apple M3 Pro und 18 GB RAM, 22 Testmails. Ausführlicher Bericht: [docs/report-qwen3.5-ollama.md](docs/report-qwen3.5-ollama.md).

| Kennzahl | Wert |
| --- | --- |
| Kategorie richtig | 21/22 (95.5 %) |
| Macro-F1 | 0.956 |
| Termin ja/nein richtig | 22/22 |
| Zeit pro Mail (nacheinander) | 2.63 s |
| Abbrüche | 0 |

Einziger Fehler: «Passwort läuft ab» wurde als `info` statt `aufgabe` eingeordnet.

### Vergleich: Cloud-API gegen lokale Modelle

Gemessen am 21.11.2026 auf denselben 22 Testmails. Cloud-API mit `python -m eval.metrics`, Gemma mit `python -m eval.benchmark --backend lmstudio --model google/gemma-4-12b-qat` (Rohdaten: [eval/results/](eval/results/)).

| Engine | Wo läuft es? | Kategorie richtig | Macro-F1 | Termin ja/nein | 22 Mails, 4 parallel |
| --- | --- | --- | --- | --- | --- |
| Cloud-API (`gpt-6-luna`) | Cloud | 21/22 (95.5 %) | 0.97 | 22/22 | 13.9 s ¹ |
| Ollama `qwen3.5:4b` | lokal | 21/22 (95.5 %) | 0.96 | 22/22 | 55.1 s |
| LM Studio `gemma-4-12b-qat` | lokal | **22/22 (100 %)** | **1.00** | 22/22 | 81.9 s |

¹ Gesamtlaufzeit des Skripts inklusive Programmstart. `eval.metrics` misst keine Zeit pro Mail, deshalb ist dieser Wert nur grob mit den lokalen vergleichbar.

Nacheinander (eine Anfrage nach der anderen) brauchten die lokalen Modelle pro Mail: Qwen 3.5 4B 2.63 s, Gemma 4 12B 6.29 s.

**Fehler im Detail:**
- **Cloud-API:** Die Spam-Mail «Verdoppeln Sie Ihr Geld» wurde nicht falsch eingeordnet, sondern vom Azure-Inhaltsfilter des Anbieters blockiert (Fehler 400). Das zeigt nebenbei, dass der Anbieter die Mail-Inhalte prüft.
- **Qwen 3.5 4B:** «Passwort läuft ab» als `info` statt `aufgabe`.
- **Gemma 4 12B:** keine Fehler.

**Einordnung:** Die lokalen Modelle erreichen auf diesem Testset dieselbe oder eine bessere Trefferquote als die Cloud-API, sind auf diesem Rechner aber langsamer. Das kleinere Modell (Qwen, 4 GB) ist schneller, das grössere (Gemma, 7 GB) genauer.

### Modellvergleich auf den Mails der App (21.11.2026)

Die 22 Testmails oben sind selbst geschrieben und eher einfach. Deshalb haben wir alle **40 Mails, die in der App liegen**, noch einmal durch drei Modelle laufen lassen: 19 ältere Mails aus dem Gmail-Testkonto und 21 Testmails von zwei Kollegen mit gezielten Grenzfällen (relatives Datum, Datum ohne Uhrzeit, Abgabe- und Zahlungsfristen, Terminabsage, zwei Termine in einer Mail, Englisch, Phishing, Prompt-Injection). 5 dieser Mails kamen doppelt an.

**Vorgehen:**
- **Baseline:** Claude Opus 5.5 hat jede Mail nach den Regeln im Prompt ([agent/prompts.py](agent/prompts.py)) eingeordnet, bevor die anderen Modelle liefen ([baseline_opus-5.5.json](eval/modellvergleich/baseline_opus-5.5.json)). 28 Fälle sind laut Prompt eindeutig («klar»), 12 regelt der Prompt nicht ausdrücklich («Ermessen»).
- **Läufe:** [eval/modellvergleich/run_model.py](eval/modellvergleich/run_model.py) ruft dieselbe Funktion wie die App auf (`analyze_email`), ohne Labels oder Kalendereinträge. Die Mails laufen nacheinander, ein Aufwärm-Aufruf zählt nicht mit.
- **Auswertung:** [eval/modellvergleich/evaluate.py](eval/modellvergleich/evaluate.py) vergleicht mit der Baseline.
- **Präsentation:** [praesentation.html](eval/modellvergleich/praesentation.html), im Browser öffnen und mit den Pfeiltasten blättern.

| | GPT-6 Luna (Cloud) | Gemma 4 12B QAT (LM Studio) | Qwen 3.5 4B (Ollama) |
| --- | --- | --- | --- |
| Parameter | keine offizielle Angabe | 12 Mrd. | 4 Mrd. |
| Übereinstimmung, 28 klare Fälle | **27/28** | 26/28 | 25/28 |
| Übereinstimmung, alle 40 Mails | 32/40 | **34/40** | 29/40 |
| Termine erkannt / exakt (von 8) | 8 / **8** | 8 / 7 | 8 / 6 |
| Terminvorschlag ohne echten Termin | 1 | 1 | 3 |
| Prompt-Injection | als Spam erkannt | `info`, wie von der Mail verlangt | folgt der Anweisung, schlägt Termin vor |
| Median pro Mail | **2.25 s** | 6.41 s | 3.34 s |
| 40 Mails gesamt | 95.7 s | 277.1 s | 127.9 s |
| Abbrüche | 0 | 0 | 0 |

**Auffällig:**
- **Datumsrechnung:** «Nächsten Dienstag um 14 Uhr», empfangen am Samstag 21.11.: Gemma und Qwen setzen Mittwoch 25.11. statt Dienstag 24.11. Qwen legt zudem «Montag 10:00» auf Dienstag.
- **Ermessensfälle:** Echte Google-Sicherheitsmails ordnet GPT-6 Luna als `aufgabe` ein (6×), Qwen als `spam` (4×). Die Baseline sagt `info`. Der Prompt regelt diesen Fall nicht.
- **Absage:** GPT-6 Luna macht aus «Meeting am Dienstag fällt aus» einen Terminvorschlag für das abgesagte Meeting.
- **Schutz in der App:** Jeder Terminvorschlag muss in der Oberfläche bestätigt werden (`confirm_event`). Falsche Vorschläge landen also nicht automatisch im Kalender.

**Grenzen dieser Evaluation:**
- **Kein Goldstandard:** Die Baseline ist die Einschätzung eines Modells, Opus 5.5 lässt sich so nicht selbst bewerten.
- **Nicht ganz blind:** Für einen Teil der älteren Mails waren frühere Ergebnisse vorher bekannt.
- **Kleine Abstände:** Bei 28 klaren Fällen trennen die Modelle 1 bis 2 Mails. Das ist kein belastbarer Abstand, und die Rangfolge kippt, sobald die Ermessensfälle mitzählen. Bei Mail Nr. 24 (Datum ohne Uhrzeit) erlaubt der Prompt `aufgabe` und `info`. Mit dieser Lesart käme GPT-6 Luna auf 28/28.
- **Ein Lauf pro Modell:** GPT-6 Luna läuft ohne gesetzte Temperatur, die Ergebnisse können schwanken.
- **Testmails:** Duplikate zählen doppelt, und die Testmails kommen von privaten Gmail-Adressen, nicht von echten Shops oder Spammern.

Der Test zeigt konkrete Schwächen (Injection, Datumsrechnung, falsche Termine). Für eine Rangliste «bestes Modell» reicht er nicht.

**Nächste Schritte:**
- Soll-Kategorien von zwei Personen festlegen lassen statt von einem Modell.
- Prompt-Regeln für Absagen, Kontobenachrichtigungen und Anweisungen in Mails ergänzen.
- Jedes Modell mehrmals laufen lassen und die Duplikate entfernen.

Die Mails selbst und die Rohergebnisse (`mails.json`, `results/`, `auswertung.json`) enthalten echte Adressen und Mailtexte und werden deshalb nicht committet.

### Nachvollziehbarkeit mit LangSmith

LangSmith zeichnet jeden Durchlauf des Agenten als **Trace** auf: welche Knoten liefen, was das Modell als Eingabe bekam, was es zurückgab, wie lange es dauerte und wie viele Tokens es brauchte. Im Code ist dafür nichts eingebaut. LangChain und LangGraph schicken die Traces automatisch, sobald in der `.env` `LANGSMITH_TRACING=true` und ein `LANGSMITH_API_KEY` stehen. Projekt: `localmail_w1`, EU-Server (`eu.api.smith.langchain.com`).

**Aufbau eines Traces** (eine Mail, echtes Beispiel aus `localmail_w1`):

```
LangGraph                       Wurzel: Eingabe = Mail, Ausgabe = Analyse + Label
├─ analyze
│  └─ ChatOpenAI  (llm)         Prompt (System + Mail) -> JSON nach Schema EmailAnalysis
│     RunnableLambda            JSON wird in EmailAnalysis umgewandelt
├─ apply_label                  Label über den MCP-Server, z. B. LocalMail/Termin
│  └─ route_after_label         Weiche: Termin gefunden -> confirm_event
└─ confirm_event                Status "interrupted": wartet auf Ja/Nein in der Oberfläche
```

Was pro LLM-Aufruf sichtbar ist: Modellname, Parameter, die vollständigen Nachrichten, die Antwort, Tokens und Laufzeit. Die `thread_id` im Trace ist die Gmail-ID der Mail, so lässt sich jede Analyse einer Mail zuordnen.

**Lokal und Cloud im Trace:** Derselbe Graph, dieselben Knoten, derselbe Prompt. Unterschiede sieht man nur im `ChatOpenAI`-Schritt:

| | Lokal (Ollama `qwen3.5:4b`) | Cloud (`gpt-6-luna`) |
| --- | --- | --- |
| Modell-Server | `localhost` | FHNW-Proxy beim Anbieter |
| Parameter im Trace | `temperature=0`, `reasoning_effort="none"` | keine `temperature` (Proxy lehnt sie ab) |
| Tokens | Eingabe und Ausgabe | zusätzlich Denk-Tokens (`reasoning`) |
| Fehlerbild | — | Fehler 400 vom Azure-Inhaltsfilter |

**Wichtig für den Datenschutz:** Ein Trace enthält die ganze Mail (Absender, Betreff, Text) und die Analyse. Mit eingeschaltetem Tracing gehen die Mail-Inhalte also an LangSmith, auch wenn das Modell lokal läuft. Für einen wirklich lokalen Betrieb `LANGSMITH_TRACING=false` setzen. Wir nutzen das Tracing nur mit Testmails und dem Gmail-Testkonto.

## 5. Limitationen

- **22 Testmails sind wenig:** Ein Fehler mehr oder weniger ändert die Genauigkeit um 4.5 Prozentpunkte. Die Testmails sind kurz (1–3 Sätze), echte Mails sind länger.
- Geprüft werden nur Kategorie und «Termin ja/nein», nicht ob Datum, Uhrzeit und Ort des Termins stimmen.
- Die Mails liegen weiterhin bei Google. Privat ist nur die KI-Auswertung, und nur mit einer lokalen Engine.
- Im Cloud-Modus gehen die Mail-Inhalte an den Cloud-Anbieter.
- Mit eingeschaltetem LangSmith-Tracing gehen die Mail-Inhalte auch an LangSmith, unabhängig von der Engine.
- Lokale Modelle brauchen einen leistungsfähigen Rechner. Die Zeiten oben gelten für einen M3 Pro.
- Im Testmodus von Google läuft die Anmeldung (`token.json`) nach 7 Tagen ab.

## 6. Technologien

| Bereich | Technologie |
| --- | --- |
| Sprache | Python |
| Agent | LangGraph (Graph, `interrupt`, SQLite-Checkpointer), LangChain |
| LLM-Zugang | `langchain-openai` (`ChatOpenAI`) mit OpenAI-kompatibler Schnittstelle |
| Lokale Modelle | Ollama, LM Studio (getestet: `qwen3.5:4b`, `gemma-4-12b-qat`) |
| Cloud-Modell | FHNW-Proxy (LiteLLM) mit `gpt-6-luna` |
| Strukturierte Ausgabe | Pydantic-Schemas (`with_structured_output`) |
| Werkzeuge | Model Context Protocol (MCP): eigener Server mit FastMCP, Client über `langchain-mcp-adapters` |
| Mail und Kalender | Gmail-API, Google-Calendar-API, OAuth über `google-auth-oauthlib` |
| Oberfläche | FastAPI, Uvicorn, HTML/CSS/JavaScript |
| Speicher | SQLite (Mails, Protokoll, Agent-Zustand) |
| Tracing | LangSmith (optional, Projekt `localmail_w1`) |
| Entwicklung | Claude Code |

---

## Guardrails im Chat

- Frage höchstens eine bestimmte Länge, Prüfung im Server
- Der Prompt erlaubt nur Fragen zu den Mails. Mails gelten als Daten, Befehle darin werden nicht befolgt.
- Erkennt das LLM eine fremde Frage (`on_topic=False`), ersetzt der Code die Antwort durch einen festen Satz.
- Eine Mail-ID vom LLM wird nur benutzt, wenn sie wirklich in der Liste stand.
- Der Chat kann nur lesen und Entwürfe anstossen. Senden, löschen oder ändern kann er nicht.
- Antworten werden als Text angezeigt, nie als HTML.

## Struktur

| Ordner / Datei | Inhalt | Rolle |
| --- | --- | --- |
| `agent/graph.py` | Der Agent: State, Knoten, Weichen, `build_graph()`, `run_agent()` (Aufbau wie Notebook 05) | Agent & LLM |
| `agent/prompts.py` | System-Prompt und Vorlage für die Mail, Prompts für Antwort-Entwürfe und Chat | Agent & LLM |
| `agent/reply.py` | Antworten: KI-Entwurf schreiben lassen, Senden erst auf Knopfdruck | Agent & LLM |
| `agent/chat.py` | Chatfenster: Fragen zu den eigenen Mails, mit Guardrails, kann Antwort-Entwürfe anstossen | Agent & LLM |
| `agent/llm.py` | KI-Engine wählen: Cloud-API, Ollama oder LM Studio | Agent & LLM |
| `agent/tools.py` | Verbindung zum MCP-Server mit `MultiServerMCPClient` (wie Notebook 06) | API & MCP |
| `agent/inbox.py` | Mails abrufen und automatisch einsortieren lassen | Agent & LLM |
| `agent/store.py` | SQLite: Mails und Protokoll speichern und lesen | alle |
| `mcp_server/server.py` | Eigener MCP-Server mit Gmail- und Kalender-Werkzeugen, auch Antworten senden (wie Notebook 06) | API & MCP |
| `mcp_server/auth.py` | Einmalige Google-Anmeldung | API & MCP |
| `app/` | Postfach-Oberfläche im Gmail-Stil: FastAPI-Server (`main.py`) und Seite in `static/` | UI |
| `eval/` | System A (Regeln), Metriken-Skript, Benchmark für lokale Modelle | Evaluation & Daten |
| `eval/data/` | Testset `testmails.json` mit Soll-Werten (wird committet) | Evaluation & Daten |
| `eval/results/` | Rohdaten der Benchmarks | Evaluation & Daten |
| `eval/modellvergleich/` | Modellvergleich auf den Mails der App: Baseline, Lauf- und Auswertungsskript, Präsentation (Mails und Rohergebnisse nur lokal) | Evaluation & Daten |
| `docs/` | Roadmap und Benchmark-Bericht zu lokalen Modellen | alle |
| `data/` | SQLite, Checkpoints – lokal, **nicht** im Repo | alle |
| `notebooks/` | Experimente | alle |
| `schemas.py` | Was das LLM zurückgeben muss (strukturierte Ausgabe, wie Notebook 05) | alle |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Keys eintragen
```

`credentials.json` (OAuth-Client «Desktop-App» aus der Google Cloud Console) ins Hauptverzeichnis legen.

## Starten

**Schnellstart mit einem Befehl** (startet LM Studio, falls installiert, öffnet den Browser und startet die App):

```bash
./start.sh        # macOS/Linux
start.bat         # Windows (LM Studio bzw. Ollama vorher selbst starten)
```

Oder von Hand:

Immer aus dem Hauptverzeichnis und als Modul, damit `from agent... import ...` und `from schemas import ...` funktionieren:

```bash
python -m app.main              # Dashboard
python -m eval.metrics          # System A (Regeln) gegen System B (LLM)
python -m eval.metrics --only-a # nur Regeln, ohne LLM-Aufrufe
python -m eval.benchmark --backend ollama --model qwen3.5:4b   # Fehlerquote und Zeit eines lokalen Modells
python -m eval.modellvergleich.run_model --backend cloud --model gpt-6-luna   # Modell auf eval/modellvergleich/mails.json
python -m eval.modellvergleich.evaluate                                     # neueste Läufe gegen die Baseline
```

Für echte Mails einmalig im Browser anmelden:

```bash
python -m mcp_server.auth
```

Die Oberfläche läuft danach unter http://127.0.0.1:7860.

Sobald `token.json` existiert, arbeitet das Postfach direkt mit Gmail: Solange die Seite offen ist, werden beim Laden und danach jede Minute die neuesten 25 Mails aus dem Posteingang geprüft, neue analysiert, in die Ordner einsortiert und in Gmail gelabelt. Kalendereinträge passieren nur nach Bestätigung. Das Kalendersymbol rechts zeigt die Termine der nächsten 14 Tage aus Google Kalender, und bei Terminvorschlägen warnt die Mail vor Überschneidungen. Im Zahnrad-Menü schaltet «Testmails statt Gmail» auf Testdaten ohne Schreibzugriffe um.

## Engine wählen (Cloud oder lokal)

Oben rechts zeigt ein Chip, welche KI-Engine gerade analysiert (grün = bereit, rot = nicht bereit). Ein Klick darauf, oder Zahnrad → «KI-Engine einrichten», öffnet den Dialog:

- **Lokal:** Die Seite sucht nach Ollama (`localhost:11434`) und LM Studio (`localhost:1234`) und listet deren Modelle. Kein API-Key nötig, die Mails verlassen den Rechner nicht.
- **Cloud-API:** Basis-URL, Modell und API-Key eines OpenAI-kompatiblen Anbieters. «Verbindung testen» fragt nur die Modellliste ab.

Ist die Engine nicht bereit (kein Key, Server aus, Modell fehlt), erscheint ein roter Hinweis, der Dialog öffnet sich beim Laden, und der Abruf pausiert, statt jede Mail als fehlgeschlagen zu markieren.

`LLM_BACKEND` in der `.env` legt nur fest, mit welcher Engine die App startet (`cloud`, `ollama` oder `lmstudio`; `proxy` ist der alte Name für `cloud`). Die Einstellungen für alle Engines dürfen gleichzeitig in der `.env` stehen.

**Für Dozierende und Teammitglieder mit eigenem Zugang:** Jede Instanz läuft auf dem eigenen Rechner und liest die eigene `.env`.

- Dauerhaft: `cp .env.example .env` und eigene Werte eintragen (`LLM_BACKEND`, Key oder lokales Modell).
- Nur für eine Sitzung: Key im Dialog eingeben. Er liegt dann nur im Arbeitsspeicher des Servers, wird nie an den Browser zurückgeschickt, nicht gespeichert, nicht protokolliert und ist nach dem Neustart weg.
- Der Server lauscht nur auf `127.0.0.1` und ist damit nur vom eigenen Rechner aus erreichbar. Nicht auf `0.0.0.0` umstellen, sonst könnten andere im Netz die eingestellte Engine samt Key mitbenutzen.

## Daten und Protokoll

- `data/localmail.sqlite` enthält die Tabellen `emails` (Mails samt Zuordnung) und `activity_log` (jede Aktion mit Zeit, Quelle und Akteur).
- Die Ansicht «Protokoll» zeigt den Verlauf und bietet ihn als Markdown zum Herunterladen an, abgelegt unter `data/protokoll.md`.
- Mail-Inhalte gehen zur Analyse an das eingestellte LLM-Backend.
- Zahnrad → «Alles zurücksetzen» löscht Mails, Analysen, Protokoll und Chat in der lokalen Datenbank und ruft danach alles neu ab (z. B. vor einer Demo). Gmail-Labels und Kalendereinträge bleiben bestehen; einen schon eingetragenen Termin nach dem Zurücksetzen nicht nochmals bestätigen, sonst steht er doppelt im Kalender.

## Bekannte Stolpersteine

- **Gmail-Aufrufe scheitern plötzlich:** Im Testmodus läuft `token.json` nach 7 Tagen ab. Datei löschen und neu anmelden.
- **Gmail-Abruf bricht mit «timed out» ab:** In manchen Netzen ist Google nicht über IPv6 erreichbar. `GOOGLE_FORCE_IPV4=1` in der `.env` setzen.
- **Nie committen:** `.env`, `credentials.json`, `token.json`, alles in `data/`.
- **`temperature` beim Proxy nicht setzen:** `gpt-6-luna` lehnt alles ausser dem Standardwert mit Fehler 400 ab.
- **Fehler 400 «content management policy»:** Der Azure-Inhaltsfilter hat eine Mail blockiert, oft Spam oder Phishing. Das Dashboard meldet sie als fehlgeschlagen und verarbeitet die übrigen weiter.
- **Lokales Modell sehr langsam:** Denkmodus ist an. `agent/llm.py` schaltet ihn für Ollama und LM Studio ab (`reasoning_effort="none"`).
