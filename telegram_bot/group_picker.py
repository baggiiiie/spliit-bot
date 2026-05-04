"""Resolve and select configured Spliit groups for Telegram flows."""

from __future__ import annotations

from telegram import Message, Update

from config import GROUPS_JSON_PATH
from domain.registry import load_group_registry
from spliit_integration.gateway import gateway
from telegram_bot.access import is_dm, resolve_group_id

NO_GROUP_MSG = "No group linked to this chat."
DM_NO_GROUP_MSG = "No group selected. Use /switch to pick one."


def configured_group_ids() -> list[str]:
    return load_group_registry(GROUPS_JSON_PATH).all_group_ids


def resolve_group(update: Update, user_data: dict | None = None) -> str | None:
    return resolve_group_id(update, user_data)


async def require_group(
    update: Update,
    user_data: dict | None,
    message: Message,
) -> str | None:
    group_id = resolve_group(update, user_data)
    if group_id:
        return group_id
    msg = DM_NO_GROUP_MSG if is_dm(update) else NO_GROUP_MSG
    await message.reply_text(msg, reply_to_message_id=message.message_id)
    return None


def group_name(group_id: str, fallback: str | None = None) -> str:
    try:
        return gateway.group(group_id).name
    except Exception:
        return fallback or group_id


def group_label(group_id: str) -> str:
    return group_name(group_id, group_id)


def group_picker_options(group_ids: list[str] | None = None) -> list[tuple[str, str]]:
    return [(group_label(group_id), group_id) for group_id in group_ids or configured_group_ids()]
