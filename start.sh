#!/bin/bash
# Startet LocalMail mit einem Befehl (macOS/Linux):  ./start.sh
#
# 1. LM-Studio-Server starten, falls LM Studio installiert ist (Port aus der .env)
# 2. Browser öffnen
# 3. Die App starten (wie: python -m app.main), beenden mit Ctrl+C

cd "$(dirname "$0")"  # immer aus dem Hauptordner, egal von wo man startet

if [ ! -x .venv/bin/python ]; then
  echo "Keine .venv gefunden. Zuerst einrichten (siehe README, Abschnitt Setup)."
  exit 1
fi

# LM Studio: Port aus LMSTUDIO_BASE_URL in der .env lesen, sonst Standardport 1234.
LMS="$HOME/.lmstudio/bin/lms"
if [ -x "$LMS" ]; then
  PORT=$(grep -E '^LMSTUDIO_BASE_URL=' .env 2>/dev/null | sed -E 's#.*:([0-9]+).*#\1#')
  "$LMS" server start --port "${PORT:-1234}" > /dev/null 2>&1 && echo "LM Studio läuft auf Port ${PORT:-1234}."
fi

# Browser erst öffnen, wenn der Server Zeit zum Starten hatte.
(sleep 3 && open "http://127.0.0.1:${APP_PORT:-7860}") &

PORT=${APP_PORT:-7860} exec .venv/bin/python -m app.main
