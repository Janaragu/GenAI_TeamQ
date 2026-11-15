# Roadmap: Lokales LLM (Ollama) anbinden

Ziel: LocalMail AI analysiert Mails vollständig lokal mit Ollama, und wir können belegen, wie gut das im Vergleich zum FHNW-Proxy funktioniert. Die Abschlusspräsentation ist am 23.11.2026 (siehe `kontext/gruppenarbeit.txt`).

## Ausgangslage (gemessen am 15.11.2026)

| Punkt | Befund |
| --- | --- |
| Hardware | MacBook mit Apple M3 Pro, 18 GB RAM |
| Ollama | Version 0.40.15, läuft unter `http://localhost:11434` |
| Installierte Modelle | `qwen3.5:4b`, `localmail:latest`, `hf.co/lmstudio-community/Qwen3.5-4B-GGUF:Q4_K_M` |
| `.env` | `OLLAMA_MODEL=qwen2.5:7b`, dieses Modell ist **nicht** installiert |
| `qwen3.5:4b` | Mit Denkmodus (Standard): Testmail 1 korrekt, aber **133 s** pro Mail. Ohne Denkmodus: Ø 3,1 s, 21/22 richtig (siehe Schritt 2). |
| `localmail:latest` | Abbruch mit `LengthFinishReasonError`: 4096 Tokens erreicht, davon 3760 Ausgabe. Das Modelfile hat `TEMPLATE {{ .Prompt }}`, d. h. kein Chat-Template; System- und User-Rolle werden nicht als Chat formatiert. |
| LangSmith | `LANGSMITH_TRACING=true` ohne Key, jeder Aufruf erzeugt `401 Unauthorized`-Meldungen |
| Oberfläche | Engine-Dialog (lokal: Ollama/LM Studio mit Erkennung, oder Cloud-API) mit Fehleranzeige ist umgesetzt (`agent/llm.py`, `app/main.py`, `app/static/`) |

## Schritte

### 1. Konfiguration bereinigen
- [ ] In `.env` `OLLAMA_MODEL=qwen3.5:4b` setzen (oder ein anderes installiertes Modell).
- [ ] LangSmith: entweder `LANGSMITH_API_KEY` eintragen oder `LANGSMITH_TRACING=false`.
- **Fertig, wenn:** Das Dashboard nach dem Start mit «Lokal (Ollama)» grün «Bereit» zeigt und keine 401-Meldungen mehr im Log stehen.

### 2. Thinking abschalten und messen ✅ (15.11.2026)
- [x] Zwei Varianten getestet (qwen3.5:4b, Testmail 1):
  - `reasoning_effort="none"`: **4,8 s**, Ergebnis korrekt
  - `extra_body={"think": False}`: 119,5 s, wirkt über `/v1` nicht
- [x] `get_llm()` setzt für Ollama `reasoning_effort="none"`.
- [x] Messung auf allen 22 Testmails, nacheinander: **21/22 Kategorien richtig, Termin ja/nein 22/22, Ø 3,1 s pro Mail (max. 5,6 s)**. Falsch: «Passwort läuft ab» (soll aufgabe, ist info).
- [x] In der App (Testmodus, 4 parallel): 22/22 analysiert, 0 Fehler, gleiche Trefferquote, **168 s für alle 22**.
- Befund für Schritt 5: Nacheinander wären es rund 68 s (22 × 3,1 s); 4 parallele Anfragen waren auf diesem Mac langsamer.
- Ursache der früheren Fehler: Mit Denkmodus liefen 4 parallele Anfragen in den 300-s-Timeout (Ollama-Log: `500 | 5m0s`).

### 3. Kontextfenster prüfen
- Der Abbruch bei `localmail:latest` lag bei 4096 Tokens. Prompt: 336 Tokens; Mailtext ist im Code auf 6000 Zeichen begrenzt (`MAX_BODY_CHARS`).
- [ ] Mit abgeschaltetem Thinking die längste Testmail laufen lassen. Reicht 4096 nicht, das Kontextfenster erhöhen (z. B. per Modelfile `PARAMETER num_ctx` oder Server-Umgebungsvariable `OLLAMA_CONTEXT_LENGTH`) und erneut messen.
- **Fertig, wenn:** Alle 22 Testmails ohne `LengthFinishReasonError` durchlaufen.

### 4. Eigenes Modell `localmail` reparieren oder weglassen
- [ ] Entscheiden, ob wir `localmail:latest` brauchen. Falls ja: Modelfile mit passendem Chat-Template neu bauen und Schritt 2–3 wiederholen. Falls nein: entfernen, damit es im Dropdown nicht verwirrt.

### 5. Parallelität abstimmen
- Dashboard (`agent/inbox.py`) und Evaluation (`eval/metrics.py`) schicken je bis zu 4 Mails gleichzeitig (`MAX_WORKERS = 4`, `max_workers=4`). Der Timeout für Ollama steht in `get_llm()` auf 300 s.
- [ ] Bei Ollama mit 1, 2 und 4 parallelen Anfragen messen, ob Timeouts auftreten und wie lange 22 Mails insgesamt brauchen. Danach die Anzahl Worker für Ollama festlegen.

### 6. Evaluation: Proxy vs. Ollama
- [ ] `eval/metrics.py` um die Zeit pro Mail ergänzen (wird bisher nicht gemessen).
- [ ] Beide Systeme auf denselben 22 Testmails laufen lassen:
  ```bash
  LLM_BACKEND=ollama OLLAMA_MODEL=qwen3.5:4b .venv/bin/python -m eval.metrics
  LLM_BACKEND=proxy .venv/bin/python -m eval.metrics
  ```
- [ ] Ergebnisse festhalten: Accuracy, Macro-F1, Termin erkannt ja/nein, Zeit pro Mail. Zusätzlich System A (Regeln) als Baseline.
- **Fertig, wenn:** Eine Tabelle mit den drei Systemen existiert, die wir in der Präsentation zeigen können.

### 7. Absichern für den Alltag
- [ ] Nach «Übernehmen» einer bereiten Engine startet sofort ein Abruf; im Gmail-Modus mit echten Mails und Labels. Für Tests immer zuerst «Testmails statt Gmail» anhaken.
- [ ] Entscheiden, ob die Engine-Wahl einen Neustart überdauern soll (heute gilt nach Neustart wieder `LLM_BACKEND` aus der `.env`).
- [ ] README um den Abschnitt «Lokal mit Ollama» ergänzen (Installation, Modell, `.env`-Werte).

## Für die Präsentation
- Mit Ollama verlassen Mail-Inhalte den Rechner nicht; beim Proxy gehen sie an das eingestellte Backend (steht so im README).
- Messwerte aus Schritt 6 als Vergleich: Qualität gegen Geschwindigkeit.
- Limitationen aus den Schritten 2–5 offen benennen (Thinking, Kontextfenster, Laufzeit auf dem Laptop).
