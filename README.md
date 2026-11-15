# LocalMail AI

LangGraph-Agent, der Mails aus einem Gmail-Testkonto kategorisiert, zusammenfasst, labelt
und Termine nach Bestätigung in Google Calendar einträgt.

## Struktur

| Ordner / Datei | Inhalt | Rolle |
| --- | --- | --- |
| `agent/` | LangGraph-Graph, State, Prompts, `run_agent()` | Agent & LLM |
| `mcp_server/` | MCP-Server mit Gmail- und Kalender-Werkzeugen | API & MCP |
| `app/` | Postfach-Oberfläche im Gmail-Stil: FastAPI-Server (`main.py`) und Seite in `static/` | UI |
| `eval/` | System A (Regeln), Metriken-Skript | Evaluation & Daten |
| `eval/data/` | Testset `testmails.json` mit Soll-Werten (wird committet) | Evaluation & Daten |
| `data/` | SQLite, Checkpoints – lokal, **nicht** im Repo | alle |
| `notebooks/` | Experimente, z.B. Ollama-Tests | alle |
| `schemas.py` | gemeinsame Pydantic-Schemas (Schnittstelle zwischen allen Teilen) | alle |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Keys eintragen
```

`credentials.json` (OAuth-Client «Desktop-App» aus der Google Cloud Console) ins Hauptverzeichnis legen.

## Starten

Immer aus dem Hauptverzeichnis und als Modul, damit `from agent... import ...` und `from schemas import ...` funktionieren:

```bash
python -m app.main              # Dashboard
python -m eval.metrics          # System A (Regeln) gegen System B (LLM)
python -m eval.metrics --only-a # nur Regeln, ohne LLM-Aufrufe
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

## Bekannte Stolpersteine

- **Gmail-Aufrufe scheitern plötzlich:** Im Testmodus läuft `token.json` nach 7 Tagen ab. Datei löschen und neu anmelden.
- **Nie committen:** `.env`, `credentials.json`, `token.json`, alles in `data/`.
- **`temperature` beim Proxy nicht setzen:** `gpt-6-luna` lehnt alles ausser dem Standardwert mit Fehler 400 ab.
- **Fehler 400 «content management policy»:** Der Azure-Inhaltsfilter hat eine Mail blockiert, oft Spam oder Phishing. Das Dashboard meldet sie als fehlgeschlagen und verarbeitet die übrigen weiter.
