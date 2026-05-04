"""Pure Telegram UI helpers and chat validation."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from config import ADMIN_TELEGRAM_USER_ID, ALLOWED_TELEGRAM_GROUP_ID, get_group_id
from constants import (
    CB_CANCEL,
    CB_CONFIRM,
    CB_PAYEE_ALL,
    CB_SELECT_GROUP,
    CB_SPLIT_MODE,
    SplitMode,
    format_money,
)


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


def confirm_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm", callback_data=f"{CB_CONFIRM}{key}"),
                InlineKeyboardButton("Cancel", callback_data=f"{CB_CANCEL}{key}"),
            ]
        ]
    )


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


def format_confirmation(
    title: str,
    amount: float,
    payer: str,
    payees: list[str],
    split_mode: SplitMode = SplitMode.EVENLY,
    paid_for_named: list[tuple[str, int]] | None = None,
    currency: str = "",
) -> str:
    """Render a pending-expense confirmation message.

    For non-``EVENLY`` modes ``paid_for_named`` must be supplied as
    ``[(name, share)]`` with share semantics matching ``split_mode``.
    """
    header = f"**{title}**\nAmount: {amount:.2f}\nPaid by: {payer}\n"
    if split_mode is SplitMode.EVENLY:
        share = amount / len(payees)
        body = f"Split: {', '.join(payees)}\nEach: {share:.2f}\n"
    else:
        assert paid_for_named is not None
        body = f"Split mode: {_split_mode_label(split_mode)}\n"
        body += "\n".join(
            f"  • {name}: {_format_share(split_mode, share, currency)}"
            for name, share in paid_for_named
        )
        body += "\n"
    return header + body + "\nConfirm?"


def _split_mode_label(mode: SplitMode) -> str:
    return {
        SplitMode.EVENLY: "Equally",
        SplitMode.BY_SHARES: "By shares",
        SplitMode.BY_PERCENTAGE: "By percentage",
        SplitMode.BY_AMOUNT: "By amount",
    }[mode]


def _format_share(mode: SplitMode, share: int, currency: str) -> str:
    if mode is SplitMode.BY_SHARES:
        return f"{share} share{'s' if share != 1 else ''}"
    if mode is SplitMode.BY_PERCENTAGE:
        return f"{share / 100:.2f}%"
    if mode is SplitMode.BY_AMOUNT:
        return format_money(share, currency)
    return str(share)


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


def tg_display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "unknown"
    return user.first_name or user.username or "unknown"


def is_dm(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.type == "private"


def resolve_group_id(update: Update, user_data: dict | None = None) -> str | None:
    if is_dm(update):
        active_group = user_data.get("active_group") if user_data else None
        return str(active_group) if active_group else None
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    return get_group_id(chat_id)


def group_picker_keyboard(group_options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"{CB_SELECT_GROUP}{group_id}")]
        for label, group_id in group_options
    ]
    return InlineKeyboardMarkup(rows)


def is_allowed_chat(update: Update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    if ADMIN_TELEGRAM_USER_ID and user_id == ADMIN_TELEGRAM_USER_ID:
        return True

    return chat_id in ALLOWED_TELEGRAM_GROUP_ID
