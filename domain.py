"""Interface-agnostic Spliit helpers shared by the bot and CLI."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from spliit import Spliit

ACTIVITY_LABELS = {
    "CREATE_EXPENSE": "Created expense",
    "UPDATE_EXPENSE": "Updated expense",
    "DELETE_EXPENSE": "Deleted expense",
    "UPDATE_GROUP": "Updated group",
}


@dataclass(frozen=True, slots=True)
class ParticipantDirectory:
    id_to_name: dict[str, str]
    name_to_id: dict[str, str]
    currency: str

    def participant_id(self, name: str) -> str | None:
        return self.name_to_id.get(name.lower())

    def participant_name(self, participant_id: str) -> str:
        return self.id_to_name.get(participant_id, participant_id)

    def unknown_names(self, names: list[str]) -> list[str]:
        return [name for name in names if not self.participant_id(name)]

    def participant_ids(self, names: list[str]) -> list[str]:
        ids: list[str] = []
        for name in names:
            participant_id = self.participant_id(name)
            assert participant_id is not None
            ids.append(participant_id)
        return ids


def participant_directory(client: Spliit) -> ParticipantDirectory:
    group = client.get_group()
    id_to_name = {str(p["id"]): str(p["name"]) for p in group["participants"]}
    return ParticipantDirectory(
        id_to_name=id_to_name,
        name_to_id={name.lower(): pid for pid, name in id_to_name.items()},
        currency=str(group["currency"]),
    )


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
