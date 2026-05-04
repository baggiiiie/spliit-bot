"""Telegram callback response helpers."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def reply_to_callback(query: Any, text: str) -> None:
    if query.message:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            logger.error(f"Failed to clear callback markup: {e}")
        await query.message.reply_text(
            text,
            reply_to_message_id=query.message.message_id,
        )
    else:
        await query.edit_message_text(text)
