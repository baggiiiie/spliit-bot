"""Telegram user-session storage for the active expense draft."""

from __future__ import annotations

from expense_draft import ExpenseDraft

DRAFT_KEY = "expense_draft"


def get_draft(user_data: dict) -> ExpenseDraft:
    draft = user_data.get(DRAFT_KEY)
    assert isinstance(draft, ExpenseDraft)
    return draft


def set_draft(user_data: dict, draft: ExpenseDraft) -> None:
    user_data[DRAFT_KEY] = draft


def clear_draft(user_data: dict) -> None:
    user_data.pop(DRAFT_KEY, None)
