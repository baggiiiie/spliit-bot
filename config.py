"""Configuration, constants, and shared state."""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from spliit import Spliit

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_TELEGRAM_USER_ID = os.getenv("ADMIN_TELEGRAM_USER_ID", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_BASE_URL = os.getenv("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")

BOT_MODE = os.getenv("BOT_MODE", "polling").lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

PROMPT_PATH: str = os.path.join(os.path.dirname(__file__), "prompt.txt")
with open(PROMPT_PATH) as f:
    PROMPT_TEMPLATE: str = f.read()


def _default_storage_path(filename: str) -> str:
    if os.path.isdir("/storage"):
        return f"/storage/{filename}"
    return os.path.join(os.path.dirname(__file__), filename)


USERS_JSON_PATH: str = os.environ.get("USERS_JSON_PATH", _default_storage_path("users.json"))
GROUPS_JSON_PATH: str = os.environ.get("GROUPS_JSON_PATH", _default_storage_path("groups.json"))

HEALTH_HTTP_PORT = int(os.getenv("HEALTH_HTTP_PORT", "0"))
try:
    with open(USERS_JSON_PATH) as f:
        SPLIIT_TO_TELEGRAM: dict[str, str] = json.load(f)
except Exception:
    SPLIIT_TO_TELEGRAM = {}

try:
    with open(GROUPS_JSON_PATH) as f:
        GROUPS: dict[str, str] = json.load(f)
except Exception:
    GROUPS = {}

ALLOWED_TELEGRAM_GROUP_ID: list[str] = list(GROUPS.keys())

ALL_GROUP_IDS: list[str] = list(dict.fromkeys(GROUPS.values()))

_spliit_clients: dict[str, Spliit] = {}


def get_spliit(group_id: str) -> Spliit:
    if group_id not in _spliit_clients:
        _spliit_clients[group_id] = Spliit(group_id=group_id)
    return _spliit_clients[group_id]


def get_group_id(chat_id: str) -> str | None:
    return GROUPS.get(chat_id)


type PaidFor = list[tuple[str, int]]
type PendingExpense = tuple[str, int, str, PaidFor, str, str]
type PendingDelete = tuple[str, str]
type PendingSettlement = tuple[str, str, int, str]

pending: dict[str, PendingExpense] = {}
pending_deletes: dict[str, PendingDelete] = {}
pending_settlements: dict[str, PendingSettlement] = {}

TITLE, AMOUNT, PAYER, PAYEES, SELECT_GROUP = range(5)
