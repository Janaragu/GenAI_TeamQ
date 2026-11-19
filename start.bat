@echo off
rem Startet LocalMail mit einem Befehl (Windows):  start.bat
rem Oeffnet den Browser und startet die App (wie: python -m app.main), beenden mit Ctrl+C.
rem LM Studio bzw. Ollama vorher selbst starten.

cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Keine .venv gefunden. Zuerst einrichten, siehe README, Abschnitt Setup.
  exit /b 1
)
start "" http://127.0.0.1:7860
.venv\Scripts\python.exe -m app.main
