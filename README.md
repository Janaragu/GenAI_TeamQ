# LocalMail AI

LangGraph-Agent, der Mails aus einem Gmail-Testkonto kategorisiert, zusammenfasst, labelt
und Termine nach Bestätigung in Google Calendar einträgt.

## Struktur

| Ordner / Datei | Inhalt | Rolle |
| --- | --- | --- |
| `agent/` | LangGraph-Graph, State, Prompts, `run_agent()` | Agent & LLM |
| `mcp_server/` | MCP-Server mit Gmail- und Kalender-Werkzeugen | API & MCP |
| `app/` | Dashboard (Gradio/Streamlit) | UI |
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

Sobald `token.json` existiert, arbeitet das Postfach direkt mit Gmail: Solange die Seite offen ist, werden beim Laden und danach jede Minute die neuesten 25 Mails aus dem Posteingang geprüft, neue analysiert, in die Ordner einsortiert und in Gmail gelabelt. Kalendereinträge passieren nur nach Bestätigung. Mit dem Haken «Testmails statt Gmail» läuft alles ohne Schreibzugriffe.

## Daten und Protokoll

- `data/localmail.sqlite` enthält die Tabellen `emails` (Mails samt Zuordnung) und `activity_log` (jede Aktion mit Zeit, Quelle und Akteur).
- Die Ansicht «Protokoll» zeigt den Verlauf und bietet ihn als Markdown zum Herunterladen an, abgelegt unter `data/protokoll.md`.
- Mail-Inhalte gehen zur Analyse an das eingestellte LLM-Backend.

## Bekannte Stolpersteine

- **Gmail-Aufrufe scheitern plötzlich:** Im Testmodus läuft `token.json` nach 7 Tagen ab. Datei löschen und neu anmelden.
- **Nie committen:** `.env`, `credentials.json`, `token.json`, alles in `data/`.
- **`temperature` beim Proxy nicht setzen:** `gpt-6-luna` lehnt alles ausser dem Standardwert mit Fehler 400 ab.
- **Fehler 400 «content management policy»:** Der Azure-Inhaltsfilter hat eine Mail blockiert, oft Spam oder Phishing. Das Dashboard meldet sie als fehlgeschlagen und verarbeitet die übrigen weiter.
