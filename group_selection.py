"""Configured Spliit group selection helpers."""

from __future__ import annotations

from spliit import Spliit

from config import ALL_GROUP_IDS, get_spliit


def group_name(client: Spliit, fallback: str) -> str:
    try:
        group = client.get_group()
    except Exception:
        return fallback
    if not isinstance(group, dict):
        return fallback
    name = group.get("name")
    return str(name) if name else fallback


def group_label(group_id: str) -> str:
    return group_name(get_spliit(group_id), group_id)


def group_picker_options(group_ids: list[str] | None = None) -> list[tuple[str, str]]:
    return [(group_label(group_id), group_id) for group_id in group_ids or ALL_GROUP_IDS]
