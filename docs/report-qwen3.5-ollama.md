# Benchmark: Qwen 3.5 4B über Ollama

Gemessen am 19.11.2026 mit `python -m eval.benchmark --backend ollama --model qwen3.5:4b`.
Rohdaten pro Mail: [`eval/results/ollama_qwen3.5_4b.json`](../eval/results/ollama_qwen3.5_4b.json).

## Einstellungen

| Was | Wert |
|---|---|
| Modell | `qwen3.5:4b` (4.5 B Parameter) |
| Quantisierung | nvfp4 (4 Bit), Ollama-Runner `mlx` |
| Server | Ollama 0.40.15, OpenAI-kompatible Schnittstelle `http://localhost:11434/v1` |
| Kontextlänge | 4096 Tokens (Ollama-Standard, laut `ollama ps`) |
| Temperatur | 0 (gesetzt in `agent/llm.py`) |
| Denkmodus | aus (`reasoning_effort="none"` in `agent/llm.py`) |
| Ausgabe | strukturiert, `with_structured_output(EmailAnalysis, method="json_schema")` |
| Prompt | `SYSTEM_PROMPT` und `USER_TEMPLATE` aus `agent/prompts.py`, Mailtext gekürzt auf 6000 Zeichen |
| Testset | 22 Mails aus `eval/data/testmails.json`, je 4–6 pro Kategorie |
| Rechner | Apple M3 Pro, 18 GB RAM, macOS |
| Ablauf | 1 Aufwärm-Anfrage (zählt nicht), dann alle 22 Mails nacheinander, dann alle 22 mit 4 parallelen Anfragen |

## Ergebnis

| Kennzahl | nacheinander | 4 parallel |
|---|---|---|
| Kategorie richtig | 21/22 (95.5 %) | 21/22 (95.5 %) |
| Macro-F1 | 0.956 | 0.956 |
| Termin ja/nein richtig | 22/22 | 22/22 |
| Abbrüche / Fehler | 0 | 0 |
| Gesamtzeit 22 Mails | 57.8 s | 55.1 s |
| Zeit pro Mail (Gesamtzeit / 22) | **2.63 s** | **2.50 s** |
| Median pro Anfrage | 2.73 s | 8.95 s |
| Langsamste Anfrage | 4.9 s | 14.8 s |

**Einziger Fehler (in beiden Durchläufen gleich):** `t10` «Passwort läuft ab» wurde als `info` statt `aufgabe` eingeordnet.

**Beobachtungen:**
- Mails mit Termin brauchen länger (3.0–4.9 s) als andere (1.2–3.2 s), weil das Modell dann zusätzlich den Termin ausgibt.
- 4 parallele Anfragen sind kaum schneller als nacheinander (55 s statt 58 s), jede einzelne Anfrage wartet aber länger (Median 9 s). Das spricht dafür, dass Ollama die Anfragen in dieser Konfiguration hintereinander abarbeitet.

## Vergleich mit Gemma (noch auszufüllen)

Gleicher Befehl, nur anderes Backend und Modell:

```bash
python -m eval.benchmark --backend lmstudio --model google/gemma-4-12b-qat
```

| Kennzahl | Qwen 3.5 4B (Ollama) | Gemma 4 12B QAT (LM Studio) |
|---|---|---|
| Kategorie richtig | 21/22 | |
| Termin ja/nein richtig | 22/22 | |
| Zeit pro Mail, nacheinander | 2.63 s | |
| Zeit pro Mail, 4 parallel | 2.50 s | |
| Modellgrösse auf der Platte | 4.0 GB | |

Hinweis: Eine frühere Messung von Gemma am selben Tag mit einem anderen Skript ergab 22/22 richtig,
etwa 5.6 s pro Mail nacheinander und 2.75 s pro Mail bei 4 parallelen Anfragen. Für einen fairen
Vergleich den Befehl oben laufen lassen.

## Grenzen der Messung

- 22 Mails sind wenig: Ein Fehler mehr oder weniger ändert die Genauigkeit um 4.5 Prozentpunkte.
- Die Testmails sind kurz (1–3 Sätze). Echte Mails sind länger und brauchen mehr Zeit.
- Geprüft werden nur Kategorie und «Termin ja/nein», nicht ob Datum, Uhrzeit und Ort des Termins stimmen.
- Die Zeiten gelten für diesen Rechner und hängen davon ab, was sonst läuft.
