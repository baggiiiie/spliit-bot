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
SPLIIT_GROUP_ID = os.getenv("SPLIIT_GROUP_ID", "")
ADMIN_TELEGRAM_USER_ID = os.getenv("ADMIN_TELEGRAM_USER_ID", "")
ALLOWED_TELEGRAM_GROUP_ID = [
    x.strip() for x in os.getenv("ALLOWED_TELEGRAM_GROUP_ID", "").split(",") if x.strip()
]

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_BASE_URL = os.getenv("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")

BOT_MODE = os.getenv("BOT_MODE", "polling").lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

spliit: Spliit | None = Spliit(group_id=SPLIIT_GROUP_ID) if SPLIIT_GROUP_ID else None

PROMPT_PATH: str = os.path.join(os.path.dirname(__file__), "prompt.txt")
with open(PROMPT_PATH) as f:
    PROMPT_TEMPLATE: str = f.read()

USERS_JSON_PATH: str = os.environ.get(
    "USERS_JSON_PATH", os.path.join(os.path.dirname(__file__), "users.json")
)
try:
    with open(USERS_JSON_PATH) as f:
        SPLIIT_TO_TELEGRAM: dict[str, str] = json.load(f)
except Exception:
    SPLIIT_TO_TELEGRAM = {}

type PaidFor = list[tuple[str, int]]
type PendingExpense = tuple[str, int, str, PaidFor, str]
type PendingSettlement = tuple[str, str, int]

pending: dict[str, PendingExpense] = {}
pending_deletes: dict[str, str] = {}
pending_settlements: dict[str, PendingSettlement] = {}

TITLE, AMOUNT, PAYER, PAYEES = range(4)
