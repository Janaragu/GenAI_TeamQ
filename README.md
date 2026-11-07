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
python -m app.main
python -m eval.metrics
```

## Bekannte Stolpersteine

- **Gmail-Aufrufe scheitern plötzlich:** Im Testmodus läuft `token.json` nach 7 Tagen ab. Datei löschen und neu anmelden.
- **Nie committen:** `.env`, `credentials.json`, `token.json`, alles in `data/`.
