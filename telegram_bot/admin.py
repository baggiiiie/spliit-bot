"""Admin reporting for failed LLM expense extraction and bot errors."""

from __future__ import annotations

import html
import logging
import traceback

from telegram import User
from telegram.ext import ContextTypes

from config import ADMIN_TELEGRAM_USER_ID

logger = logging.getLogger(__name__)


async def _notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not ADMIN_TELEGRAM_USER_ID:
        return
    await context.bot.send_message(
        chat_id=ADMIN_TELEGRAM_USER_ID,
        text=text,
        parse_mode="HTML",
    )


async def notify_admin_llm_error(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    raw_text: str,
    error: str,
    raw_response: str | None,
) -> None:
    try:
        user_info = f"@{user.username}" if user.username else f"ID: {user.id}"
        await _notify_admin(
            context,
            (
                f"⚠️ <b>LLM Parsing failed</b> for {html.escape(user_info)}\n\n"
                f"<b>Input:</b> <code>{html.escape(str(raw_text))}</code>\n"
                f"<b>Error:</b> {html.escape(str(error))}\n"
                f"<b>Raw Response:</b>\n<pre>{html.escape(str(raw_response))}</pre>"
            ),
        )
    except Exception as e:
        logger.error("Failed to send error report to admin: %s", e)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.error:
        return
    tb = "".join(traceback.format_exception(context.error))
    logger.error("Exception:\n%s", tb)
    try:
        await _notify_admin(context, f"⚠️ Bot error:\n<pre>{html.escape(tb)}</pre>")
    except Exception as e:
        logger.error("Failed to notify admin: %s", e)
