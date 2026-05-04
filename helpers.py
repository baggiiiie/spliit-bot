"""Telegram chat identity and access helpers."""

from __future__ import annotations

from telegram import Update

from config import ADMIN_TELEGRAM_USER_ID, ALLOWED_TELEGRAM_GROUP_ID, get_group_id
from user_session import active_group_id


def tg_display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "unknown"
    return user.first_name or user.username or "unknown"


def is_dm(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.type == "private"


def resolve_group_id(update: Update, user_data: dict | None = None) -> str | None:
    if is_dm(update):
        return active_group_id(user_data)
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    return get_group_id(chat_id)


def is_allowed_chat(update: Update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    if ADMIN_TELEGRAM_USER_ID and user_id == ADMIN_TELEGRAM_USER_ID:
        return True

    return chat_id in ALLOWED_TELEGRAM_GROUP_ID
