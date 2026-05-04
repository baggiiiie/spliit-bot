from __future__ import annotations

import html
from dataclasses import dataclass

ACTIVITY_LABELS = {
    "CREATE_EXPENSE": "Created expense",
    "UPDATE_EXPENSE": "Updated expense",
    "DELETE_EXPENSE": "Deleted expense",
    "UPDATE_GROUP": "Updated group",
}


@dataclass(frozen=True, slots=True)
class Activity:
    activity_type: str
    subject: str
    expense_id: str | None = None


def activity_label(activity_type: str) -> str:
    return ACTIVITY_LABELS.get(activity_type, activity_type)


def format_activity_line_html(activity: Activity, index: int) -> str:
    label = activity_label(activity.activity_type)
    subject = html.escape(activity.subject)
    return f"{index}. <b>{label}</b>: {subject}"


def format_activity_line_text(activity: Activity, index: int) -> str:
    return f"{index}. {activity_label(activity.activity_type)}: {activity.subject}"


def undoable_activity(activity: Activity) -> tuple[str, str] | None:
    if activity.activity_type != "CREATE_EXPENSE" or not activity.expense_id:
        return None
    return activity.expense_id, activity.subject
