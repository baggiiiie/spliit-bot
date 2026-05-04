"""Resolve the Spliit group targeted by a Telegram update."""

from __future__ import annotations

from spliit import Spliit
from telegram import Message, Update

from config import get_spliit
from helpers import is_dm, resolve_group_id

NO_GROUP_MSG = "No group linked to this chat."
DM_NO_GROUP_MSG = "No group selected. Use /switch to pick one."


def resolve_group(update: Update, user_data: dict | None = None) -> tuple[str, Spliit] | None:
    group_id = resolve_group_id(update, user_data)
    if not group_id:
        return None
    return group_id, get_spliit(group_id)


async def require_group(
    update: Update,
    user_data: dict | None,
    message: Message,
) -> tuple[str, Spliit] | None:
    resolved = resolve_group(update, user_data)
    if resolved:
        return resolved
    msg = DM_NO_GROUP_MSG if is_dm(update) else NO_GROUP_MSG
    await message.reply_text(msg, reply_to_message_id=message.message_id)
    return None
