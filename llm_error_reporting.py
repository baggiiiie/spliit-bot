"""Admin reporting for failed LLM expense extraction."""

from __future__ import annotations

import html
import logging
from typing import Any

from telegram.ext import ContextTypes

from config import ADMIN_TELEGRAM_USER_ID

logger = logging.getLogger(__name__)


async def notify_admin_llm_error(
    context: ContextTypes.DEFAULT_TYPE,
    user: Any,
    raw_text: str,
    error: str,
    raw_response: str | None,
) -> None:
    if not ADMIN_TELEGRAM_USER_ID:
        return
    try:
        user_info = f"@{user.username}" if user.username else f"ID: {user.id}"
        await context.bot.send_message(
            chat_id=ADMIN_TELEGRAM_USER_ID,
            text=(
                f"⚠️ <b>LLM Parsing failed</b> for {html.escape(user_info)}\n\n"
                f"<b>Input:</b> <code>{html.escape(str(raw_text))}</code>\n"
                f"<b>Error:</b> {html.escape(str(error))}\n"
                f"<b>Raw Response:</b>\n<pre>{html.escape(str(raw_response))}</pre>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to send error report to admin: {e}")
