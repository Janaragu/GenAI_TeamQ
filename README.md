# LocalMail AI

LangGraph-Agent, der Mails aus einem Gmail-Testkonto kategorisiert, zusammenfasst, labelt
und Termine nach Bestätigung in Google Calendar einträgt.

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
| `eval/` | System A (Regeln), Metriken-Skript | Evaluation & Daten |
| `eval/data/` | Testset `testmails.json` mit Soll-Werten (wird committet) | Evaluation & Daten |
| `data/` | SQLite, Checkpoints – lokal, **nicht** im Repo | alle |
| `notebooks/` | Experimente, z.B. Ollama-Tests | alle |
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
- **Nie committen:** `.env`, `credentials.json`, `token.json`, alles in `data/`.
- **`temperature` beim Proxy nicht setzen:** `gpt-6-luna` lehnt alles ausser dem Standardwert mit Fehler 400 ab.
- **Fehler 400 «content management policy»:** Der Azure-Inhaltsfilter hat eine Mail blockiert, oft Spam oder Phishing. Das Dashboard meldet sie als fehlgeschlagen und verarbeitet die übrigen weiter.
