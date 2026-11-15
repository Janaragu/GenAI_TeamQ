"""Wählt und baut das Chat-Modell ("Engine").

Startwerte kommen aus der .env (LLM_BACKEND). Im Dashboard lässt sich die Engine zur Laufzeit
umstellen. Diese Auswahl, auch ein dort eingegebener API-Key, liegt nur im Arbeitsspeicher
des laufenden Prozesses: nichts davon wird in Dateien, die Datenbank oder das Protokoll geschrieben.
"""

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

CLOUD = "cloud"
OLLAMA = "ollama"
LMSTUDIO = "lmstudio"
LOCAL_PROVIDERS = (OLLAMA, LMSTUDIO)
PROVIDER_NAMES = {CLOUD: "Cloud-API", OLLAMA: "Ollama (lokal)", LMSTUDIO: "LM Studio (lokal)"}
DEFAULT_URLS = {OLLAMA: "http://localhost:11434/v1", LMSTUDIO: "http://localhost:1234/v1"}

# Lokale Server prüfen keinen Key, die OpenAI-Bibliothek verlangt aber einen nicht leeren Wert.
LOCAL_PLACEHOLDER_KEY = "local"


@dataclass(frozen=True)
class EngineConfig:
    provider: str
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)  # nie in Logs oder Fehlermeldungen ausgeben

    @property
    def name(self) -> str:
        return PROVIDER_NAMES[self.provider]

    @property
    def is_local(self) -> bool:
        return self.provider in LOCAL_PROVIDERS


@dataclass
class EngineStatus:
    config: EngineConfig
    ready: bool
    problem: str = ""

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model


def local_url(provider: str) -> str:
    return os.getenv(f"{provider.upper()}_BASE_URL", DEFAULT_URLS[provider]).rstrip("/")


def cloud_from_env() -> EngineConfig:
    return EngineConfig(
        CLOUD,
        os.getenv("OPENAI_BASE_URL", "").rstrip("/"),
        os.getenv("OPENAI_MODEL", ""),
        os.getenv("OPENAI_API_KEY", ""),
    )


def _from_env() -> EngineConfig:
    backend = os.getenv("LLM_BACKEND", CLOUD).lower()
    if backend in ("proxy", CLOUD):
        return cloud_from_env()
    if backend in LOCAL_PROVIDERS:
        return EngineConfig(backend, local_url(backend), os.getenv(f"{backend.upper()}_MODEL", ""))
    raise ValueError(f"Unbekanntes LLM_BACKEND: {backend!r} (erlaubt: cloud, proxy, ollama, lmstudio)")


_lock = threading.Lock()
_current: EngineConfig | None = None


def current_config() -> EngineConfig:
    with _lock:
        if _current is None:
            return _from_env()
        return _current


def set_config(config: EngineConfig) -> None:
    """Gilt sofort für alle folgenden Analysen dieses Prozesses, bis zum Neustart."""
    global _current
    if config.provider not in PROVIDER_NAMES:
        raise ValueError(f"Unbekannter Anbieter: {config.provider!r}")
    with _lock:
        _current = replace(config, base_url=config.base_url.rstrip("/"))


class ConnectionProblem(Exception):
    pass


def fetch_models(base_url: str, api_key: str = "", timeout: float = 3) -> list[str]:
    """Fragt die OpenAI-kompatible Modellliste ab. Funktioniert für Ollama, LM Studio und viele Cloud-APIs."""
    request = urllib.request.Request(f"{base_url.rstrip('/')}/models")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ConnectionProblem(f"Zugriff verweigert (HTTP {error.code}): API-Key prüfen.") from None
        raise ConnectionProblem(f"Server antwortet mit HTTP {error.code}.") from None
    except (OSError, ValueError):
        raise ConnectionProblem(f"Unter {base_url} ist kein Server erreichbar.") from None
    return [item["id"] for item in data.get("data", []) if "id" in item]


def detect_local() -> dict[str, list[str] | None]:
    """Welche lokalen Server laufen gerade? None = nicht erreichbar, sonst die geladenen Modelle."""
    found = {}
    for provider in LOCAL_PROVIDERS:
        try:
            found[provider] = fetch_models(local_url(provider), timeout=1.5)
        except ConnectionProblem:
            found[provider] = None
    return found


def engine_status() -> EngineStatus:
    """Prüft, ob die gewählte Engine benutzbar ist, ohne ein Modell aufzurufen."""
    config = current_config()
    if config.provider == CLOUD:
        missing = [
            label
            for label, value in (("Basis-URL", config.base_url), ("Modell", config.model), ("API-Key", config.api_key))
            if not value
        ]
        if missing:
            return EngineStatus(config, False, f"Es fehlt: {', '.join(missing)}. In den Engine-Einstellungen oder der .env eintragen.")
        return EngineStatus(config, True)

    try:
        models = fetch_models(config.base_url, timeout=1.5)
    except ConnectionProblem as problem:
        return EngineStatus(config, False, f"{problem} Läuft {config.name.split(' ')[0]}?")
    if not config.model:
        return EngineStatus(config, False, "Kein Modell gewählt.")
    if config.model not in models:
        return EngineStatus(config, False, f"Modell {config.model} ist auf diesem Server nicht verfügbar.")
    return EngineStatus(config, True)


def get_llm() -> ChatOpenAI:
    config = current_config()
    if config.provider == CLOUD:
        # Keine temperature setzen: Die Reasoning-Modelle am FHNW-Proxy lehnen alles ausser 1 ab.
        return ChatOpenAI(model=config.model, base_url=config.base_url, api_key=config.api_key, timeout=120)
    return ChatOpenAI(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key or LOCAL_PLACEHOLDER_KEY,
        temperature=0,
        timeout=300,
    )
