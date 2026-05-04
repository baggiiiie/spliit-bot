"""Telegram mention rendering for Spliit participant names."""

from __future__ import annotations

from telegram.ext import ContextTypes

from config import SPLIIT_TO_TELEGRAM


async def build_mention(name: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    tg_id = SPLIIT_TO_TELEGRAM.get(name.lower())
    if not tg_id:
        return name
    try:
        chat = await context.bot.get_chat(int(tg_id))
        if chat.username:
            return f"@{chat.username}"
        display = chat.first_name or name
        return f'<a href="tg://user?id={tg_id}">{display}</a>'
    except Exception:
        return f'<a href="tg://user?id={tg_id}">{name}</a>'
