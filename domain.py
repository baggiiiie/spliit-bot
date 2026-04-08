"""Interface-agnostic Spliit helpers shared by the bot and CLI."""

from __future__ import annotations

import html
from typing import Any

from spliit import Spliit

from config import ALL_GROUP_IDS, get_spliit

ACTIVITY_LABELS = {
    "CREATE_EXPENSE": "Created expense",
    "UPDATE_EXPENSE": "Updated expense",
    "DELETE_EXPENSE": "Deleted expense",
    "UPDATE_GROUP": "Updated group",
}


def id_to_name_map(client: Spliit) -> tuple[dict[str, str], str]:
    group = client.get_group()
    return {str(p["id"]): str(p["name"]) for p in group["participants"]}, str(group["currency"])


def group_label(group_id: str) -> str:
    client = get_spliit(group_id)
    try:
        group = client.get_group()
    except Exception:
        return group_id
    if not isinstance(group, dict):
        return group_id
    name = group.get("name")
    return str(name) if name else group_id


def group_picker_options(group_ids: list[str] | None = None) -> list[tuple[str, str]]:
    return [(group_label(group_id), group_id) for group_id in group_ids or ALL_GROUP_IDS]


def activity_label(activity_type: str) -> str:
    return ACTIVITY_LABELS.get(activity_type, activity_type)


def activity_subject(activity: dict[str, Any]) -> str:
    if activity.get("data"):
        return str(activity["data"])
    if expense := activity.get("expense"):
        return str(expense.get("title", "Untitled"))
    return "Untitled"


def format_activity_line_html(activity: dict[str, Any], index: int) -> str:
    label = activity_label(str(activity["activityType"]))
    subject = html.escape(activity_subject(activity))
    return f"{index}. <b>{label}</b>: {subject}"


def format_activity_line_text(activity: dict[str, Any], index: int) -> str:
    label = activity_label(str(activity["activityType"]))
    return f"{index}. {label}: {activity_subject(activity)}"


def undoable_activity(activity: dict[str, Any]) -> tuple[str, str] | None:
    if str(activity.get("activityType")) != "CREATE_EXPENSE":
        return None
    expense_id = activity.get("expenseId")
    if not expense_id or not activity.get("expense"):
        return None
    return str(expense_id), activity_subject(activity)
