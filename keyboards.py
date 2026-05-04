"""Telegram inline keyboard builders."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from constants import CB_PAYEE_ALL, CB_SELECT_GROUP, CB_SPLIT_MODE, SplitMode


def participant_keyboard(
    participants: dict[str, str],
    prefix: str,
    selected: set[str] | None = None,
    done_btn: tuple[str, str] | None = None,
) -> InlineKeyboardMarkup:
    selected = selected or set()
    rows = [
        [
            InlineKeyboardButton(
                f"{'✓ ' if pid in selected else ''}{name}",
                callback_data=f"{prefix}{pid}",
            )
        ]
        for name, pid in participants.items()
    ]
    if done_btn:
        all_selected = selected == set(participants.values())
        rows.append(
            [
                InlineKeyboardButton(
                    "Deselect All" if all_selected else "Select All",
                    callback_data=f"{prefix}{CB_PAYEE_ALL}",
                ),
                InlineKeyboardButton(done_btn[0], callback_data=done_btn[1]),
            ]
        )
    return InlineKeyboardMarkup(rows)


def reimbursement_keyboard(
    options: list[tuple[str, str]], cancel_btn: tuple[str, str] | None = None
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=callback_data)]
        for label, callback_data in options
    ]
    if cancel_btn:
        rows.append([InlineKeyboardButton(cancel_btn[0], callback_data=cancel_btn[1])])
    return InlineKeyboardMarkup(rows)


def split_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Equally", callback_data=f"{CB_SPLIT_MODE}{SplitMode.EVENLY.value}"
                ),
                InlineKeyboardButton(
                    "Shares", callback_data=f"{CB_SPLIT_MODE}{SplitMode.BY_SHARES.value}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "Percent", callback_data=f"{CB_SPLIT_MODE}{SplitMode.BY_PERCENTAGE.value}"
                ),
                InlineKeyboardButton(
                    "Amount", callback_data=f"{CB_SPLIT_MODE}{SplitMode.BY_AMOUNT.value}"
                ),
            ],
        ]
    )


def group_picker_keyboard(group_options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"{CB_SELECT_GROUP}{group_id}")]
        for label, group_id in group_options
    ]
    return InlineKeyboardMarkup(rows)
