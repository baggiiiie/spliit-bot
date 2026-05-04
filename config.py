"""Configuration and environment-backed settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_TELEGRAM_USER_ID = os.getenv("ADMIN_TELEGRAM_USER_ID", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_BASE_URL = os.getenv("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")

BOT_MODE = os.getenv("BOT_MODE", "polling").lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
HEALTH_HTTP_PORT = int(os.getenv("HEALTH_HTTP_PORT", "0"))

BASE_DIR = Path(__file__).resolve().parent


def _default_storage_path(filename: str) -> str:
    if os.path.isdir("/storage"):
        return f"/storage/{filename}"
    return str(BASE_DIR / filename)


USERS_JSON_PATH = os.environ.get("USERS_JSON_PATH", _default_storage_path("users.json"))
GROUPS_JSON_PATH = os.environ.get("GROUPS_JSON_PATH", _default_storage_path("groups.json"))
