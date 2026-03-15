"""Telegram UI helpers and utility functions."""

from __future__ import annotations

from spliit import Spliit
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ADMIN_TELEGRAM_USER_ID, ALLOWED_TELEGRAM_GROUP_ID, SPLIIT_TO_TELEGRAM


def id_to_name_map(client: Spliit) -> tuple[dict[str, str], str]:
    group = client.get_group()
    return {p["id"]: p["name"] for p in group["participants"]}, group["currency"]


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
                    callback_data=f"{prefix}all",
                ),
                InlineKeyboardButton(done_btn[0], callback_data=done_btn[1]),
            ]
        )
    return InlineKeyboardMarkup(rows)


def confirm_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm", callback_data=f"yes_{key}"),
                InlineKeyboardButton("Cancel", callback_data=f"no_{key}"),
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


def format_confirmation(title: str, amount: float, payer: str, payees: list[str]) -> str:
    share = amount / len(payees)
    return (
        f"**{title}**\n"
        f"Amount: {amount:.2f}\n"
        f"Paid by: {payer}\n"
        f"Split: {', '.join(payees)}\n"
        f"Each: {share:.2f}\n\n"
        f"Confirm?"
    )


def tg_display_name(update: Update) -> str:
    u = update.effective_user
    if not u:
        return "unknown"
    return u.first_name or u.username or "unknown"


async def build_mention(name: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    tg_id = SPLIIT_TO_TELEGRAM.get(name.lower())
    if not tg_id:
        return name
    try:
        chat = await context.bot.get_chat(int(tg_id))
        if chat.username:
            return f"@{chat.username}"
        display = chat.first_name or name
        return f'<a href="tg://user?id={tg_id}">{display}</a>'
    except Exception:
        return f'<a href="tg://user?id={tg_id}">{name}</a>'


def is_allowed_chat(update: Update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    if ADMIN_TELEGRAM_USER_ID and user_id == ADMIN_TELEGRAM_USER_ID:
        return True

    return chat_id in ALLOWED_TELEGRAM_GROUP_ID
