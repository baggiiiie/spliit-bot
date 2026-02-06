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
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID", "")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "")
OPENCODE_CLI = os.getenv("OPENCODE_CLI", "opencode")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "opencode/kimi-k2.5-free")

BOT_MODE = os.getenv("BOT_MODE", "polling").lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

spliit: Spliit | None = Spliit(group_id=SPLIIT_GROUP_ID) if SPLIIT_GROUP_ID else None

PROMPT_PATH: str = os.path.join(os.path.dirname(__file__), "prompt.txt")
with open(PROMPT_PATH) as f:
    PROMPT_TEMPLATE: str = f.read()

USERS_JSON_PATH: str = os.path.join(os.path.dirname(__file__), "users.json")
try:
    with open(USERS_JSON_PATH) as f:
        SPLIIT_TO_TELEGRAM: dict[str, str] = json.load(f)
except Exception:
    SPLIIT_TO_TELEGRAM = {}

type PaidFor = list[tuple[str, int]]
type PendingExpense = tuple[str, int, str, PaidFor, str]

pending: dict[str, PendingExpense] = {}

TITLE, AMOUNT, PAYER, PAYEES = range(4)
