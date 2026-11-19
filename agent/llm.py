"""Wählt und baut das Sprachmodell, die "KI-Engine".

Drei Möglichkeiten, alle über dieselbe OpenAI-kompatible Schnittstelle (ChatOpenAI):
  cloud     Cloud-API mit Key, z. B. der FHNW-Proxy
  ollama    lokaler Ollama-Server, kein Key nötig
  lmstudio  lokaler LM-Studio-Server, kein Key nötig

Der Startwert kommt aus der .env (LLM_BACKEND). In der Oberfläche lässt sich die
Engine umstellen. Die Auswahl, auch ein dort eingegebener API-Key, steht nur in der
Variable `engine` unten, also im Arbeitsspeicher: nichts davon wird gespeichert.
"""

import os

import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

NAMES = {"cloud": "Cloud-API", "ollama": "Ollama (lokal)", "lmstudio": "LM Studio (lokal)"}
LOCAL = ["ollama", "lmstudio"]
DEFAULT_URLS = {"ollama": "http://localhost:11434/v1", "lmstudio": "http://localhost:1234/v1"}


# -----------------------------------------------------------------------------
# 1. Einstellungen aus der .env lesen
# -----------------------------------------------------------------------------
def local_url(provider):
    """Adresse eines lokalen Servers: aus der .env, sonst der Standardport."""
    return os.getenv(f"{provider.upper()}_BASE_URL", DEFAULT_URLS[provider]).rstrip("/")


def cloud_from_env():
    """Cloud-Einstellungen aus der .env."""
    return {
        "provider": "cloud",
        "base_url": os.getenv("OPENAI_BASE_URL", "").rstrip("/"),
        "model": os.getenv("OPENAI_MODEL", ""),
        "api_key": os.getenv("OPENAI_API_KEY", ""),
    }


def engine_from_env():
    """Startwert der Engine, je nach LLM_BACKEND in der .env."""
    backend = os.getenv("LLM_BACKEND", "cloud").lower()
    if backend in ("cloud", "proxy"):  # "proxy" ist der alte Name für "cloud"
        return cloud_from_env()
    if backend in LOCAL:
        model = os.getenv(f"{backend.upper()}_MODEL", "")
        return {"provider": backend, "base_url": local_url(backend), "model": model, "api_key": ""}
    raise ValueError(f"Unbekanntes LLM_BACKEND: {backend!r} (erlaubt: cloud, proxy, ollama, lmstudio)")


# Die gerade gewählte Engine. app/main.py ersetzt sie, wenn jemand im Dialog umstellt.
# Immer als llm.engine lesen, nicht mit "from agent.llm import engine" kopieren,
# sonst sieht man eine Umstellung nicht.
engine = engine_from_env()


# -----------------------------------------------------------------------------
# 2. Prüfen, ob ein Server erreichbar ist und welche Modelle er hat
#    Fragt nur die Modellliste ab (/models), ruft also kein Modell auf.
# -----------------------------------------------------------------------------
class ConnectionProblem(Exception):
    """Server nicht erreichbar oder Zugriff verweigert. Der Text wird in der Oberfläche angezeigt."""


def list_models(base_url, api_key="", timeout=3):
    """Namen der Modelle, die ein OpenAI-kompatibler Server anbietet."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = requests.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout)
        if response.status_code in (401, 403):
            raise ConnectionProblem(f"Zugriff verweigert (HTTP {response.status_code}): API-Key prüfen.")
        if not response.ok:
            raise ConnectionProblem(f"Server antwortet mit HTTP {response.status_code}.")
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ConnectionProblem(f"Unter {base_url} ist kein Server erreichbar.") from None
    return [item["id"] for item in data.get("data", []) if "id" in item]


def local_servers():
    """Welche lokalen Server laufen? Pro Server die Modellliste, oder None, wenn er nicht antwortet."""
    found = {}
    for provider in LOCAL:
        try:
            found[provider] = list_models(local_url(provider), timeout=1.5)
        except ConnectionProblem:
            found[provider] = None
    return found


def engine_problem():
    """Leerer Text, wenn die Engine benutzbar ist, sonst eine Erklärung, was fehlt."""
    if engine["provider"] == "cloud":
        missing = [
            label
            for label, key in (("Basis-URL", "base_url"), ("Modell", "model"), ("API-Key", "api_key"))
            if not engine[key]
        ]
        if missing:
            return f"Es fehlt: {', '.join(missing)}. In den Engine-Einstellungen oder der .env eintragen."
        return ""

    name = NAMES[engine["provider"]].split(" ")[0]  # "Ollama" oder "LM"
    try:
        models = list_models(engine["base_url"], timeout=1.5)
    except ConnectionProblem as problem:
        return f"{problem} Läuft {name}?"
    if not engine["model"]:
        return "Kein Modell gewählt."
    if engine["model"] not in models:
        return f"Modell {engine['model']} ist auf diesem Server nicht verfügbar."
    return ""


# -----------------------------------------------------------------------------
# 3. Das Modell bauen (wie im Notebook 04: ChatOpenAI mit model, base_url, api_key)
# -----------------------------------------------------------------------------
def get_llm():
    if engine["provider"] == "cloud":
        # Keine temperature setzen: Die Reasoning-Modelle am FHNW-Proxy lehnen alles ausser 1 ab.
        return ChatOpenAI(
            model=engine["model"],
            base_url=engine["base_url"],
            api_key=engine["api_key"],
            timeout=120,
        )

    # Denkmodus aus, bei Ollama und LM Studio:
    # - Ollama, qwen3.5:4b: eine Mail dauerte sonst ~120 s statt ~3 s, und vier parallele
    #   Anfragen liefen in den Timeout. Gemessen am 15.11.2026 auf den 22 Testmails:
    #   21/22 Kategorien richtig. extra_body={"think": False} wirkte über /v1 nicht.
    # - LM Studio, google/gemma-4-12b-qat: denkt ebenfalls standardmässig, ~60-70 s pro Mail.
    #   Mit reasoning_effort="none" keine Denk-Tokens mehr (gemessen am 19.11.2026).
    extra = {"reasoning_effort": "none"}
    return ChatOpenAI(
        model=engine["model"],
        base_url=engine["base_url"],
        # Lokale Server prüfen keinen Key, ChatOpenAI verlangt aber irgendeinen Wert.
        api_key=engine["api_key"] or "local",
        temperature=0,
        timeout=300,
        **extra,
    )
