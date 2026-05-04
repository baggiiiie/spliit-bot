"""Typed helpers for Telegram per-user session data."""

from __future__ import annotations

ACTIVE_GROUP_KEY = "active_group"
PENDING_CMD_KEY = "pending_cmd"
PENDING_CMD_TEXT_KEY = "pending_cmd_text"
ADD_PENDING_CMD = "add"


def active_group_id(user_data: dict | None) -> str | None:
    active_group = user_data.get(ACTIVE_GROUP_KEY) if user_data else None
    return str(active_group) if active_group else None


def set_active_group(user_data: dict, group_id: str) -> None:
    user_data[ACTIVE_GROUP_KEY] = group_id


def remember_pending_add(user_data: dict, text: str) -> None:
    user_data[PENDING_CMD_KEY] = ADD_PENDING_CMD
    user_data[PENDING_CMD_TEXT_KEY] = text


def pop_pending_add(user_data: dict) -> str | None:
    pending_cmd = user_data.pop(PENDING_CMD_KEY, None)
    pending_text = user_data.pop(PENDING_CMD_TEXT_KEY, None)
    if pending_cmd != ADD_PENDING_CMD:
        return None
    return str(pending_text) if pending_text else "/add"
