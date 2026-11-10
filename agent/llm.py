"""Baut das Chat-Modell je nach LLM_BACKEND in der .env."""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def get_llm() -> ChatOpenAI:
    backend = os.getenv("LLM_BACKEND", "proxy").lower()
    if backend == "proxy":
        # Keine temperature setzen: Die Reasoning-Modelle am Proxy lehnen alles ausser 1 ab.
        return ChatOpenAI(
            model=os.environ["OPENAI_MODEL"],
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=120,
        )
    if backend == "ollama":
        return ChatOpenAI(
            model=os.environ["OLLAMA_MODEL"],
            base_url=os.environ["OLLAMA_BASE_URL"],
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            temperature=0,
            timeout=300,
        )
    raise ValueError(f"Unbekanntes LLM_BACKEND: {backend!r} (erlaubt: proxy, ollama)")
