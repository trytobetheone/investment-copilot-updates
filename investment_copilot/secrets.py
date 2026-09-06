from __future__ import annotations

import os

try:
    import keyring
except Exception:  # pragma: no cover
    keyring = None

from .config import settings


def get_openai_api_key() -> str | None:
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key
    if keyring is None:
        return None
    try:
        return keyring.get_password(settings.service_name, "OPENAI_API_KEY")
    except Exception:
        return None


def save_openai_api_key(value: str) -> None:
    value = value.strip()
    if not value:
        raise ValueError("API key is empty")
    if keyring is None:
        raise RuntimeError("keyring package is unavailable")
    keyring.set_password(settings.service_name, "OPENAI_API_KEY", value)
