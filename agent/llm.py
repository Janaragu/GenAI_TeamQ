"""Erzeugt das Sprachmodell (LLM), mit dem der Agent arbeitet.

Welches Modell benutzt wird, steht in der .env unter LLM_BACKEND:
  proxy  = FHNW-Proxy (OpenAI-kompatibel), für die Entwicklung
  ollama = lokales Modell auf dem eigenen Rechner
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def get_llm() -> ChatOpenAI:
    backend = os.getenv("LLM_BACKEND", "proxy").lower()

    # --- FHNW-Proxy ----------------------------------------------------------
    # Keine temperature setzen: Die Reasoning-Modelle am Proxy lehnen alles
    # ausser dem Standardwert mit Fehler 400 ab.
    if backend == "proxy":
        return ChatOpenAI(
            model=os.environ["OPENAI_MODEL"],
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=120,
        )

    # --- Ollama (lokal) ------------------------------------------------------
    # temperature=0 macht die Antworten möglichst gleichbleibend.
    if backend == "ollama":
        return ChatOpenAI(
            model=os.environ["OLLAMA_MODEL"],
            base_url=os.environ["OLLAMA_BASE_URL"],
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            temperature=0,
            timeout=300,
        )

    raise ValueError(f"Unbekanntes LLM_BACKEND: {backend!r} (erlaubt: proxy, ollama)")
