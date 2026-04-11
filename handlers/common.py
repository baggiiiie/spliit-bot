"""Shared handler utilities (no command/callback handlers live here)."""

from __future__ import annotations

import html
import logging
from typing import Any

from spliit import Spliit
from telegram import InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from config import (
    ADMIN_TELEGRAM_USER_ID,
    get_spliit,
    pending,
)
from constants import (
    PendingExpense,
)
from helpers import (
    confirm_keyboard,
    format_confirmation,
    is_dm,
    resolve_group_id,
)

logger = logging.getLogger(__name__)

FORMAT_HELP = "Format: `/add title, amount, names`"
NO_GROUP_MSG = "No group linked to this chat."
DM_NO_GROUP_MSG = "No group selected. Use /switch to pick one."


def resolve_group(update: Update, user_data: dict | None = None) -> tuple[str, Spliit] | None:
    group_id = resolve_group_id(update, user_data)
    if not group_id:
        return None
    return group_id, get_spliit(group_id)


async def build_mention(name: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    from config import SPLIIT_TO_TELEGRAM

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


async def reply_to_callback(query: Any, text: str) -> None:
    if query.message:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            logger.error(f"Failed to clear callback markup: {e}")
        await query.message.reply_text(
            text,
            reply_to_message_id=query.message.message_id,
        )
    else:
        await query.edit_message_text(text)


def _parse_count_arg(context: ContextTypes.DEFAULT_TYPE, default: int) -> int | str:
    if not context.args:
        return default
    try:
        count = int(context.args[0])
    except ValueError:
        return "Count must be a positive integer."
    if count < 1:
        return "Count must be a positive integer."
    return count


async def _require_group(
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


def _group_name(client: Spliit, group_id: str) -> str:
    try:
        group = client.get_group()
    except Exception:
        return group_id
    if not isinstance(group, dict):
        return group_id
    name = group.get("name")
    return str(name) if name else group_id


def _store_pending_expense(
    user_data: dict,
    user_id: int,
    message_id: int,
    tg_name: str,
    payee_ids: list[str],
    group_id: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build confirmation for a pending expense and store it."""
    title = user_data["expense_title"]
    amount = user_data["expense_amount"]
    payer_id = user_data["payer_id"]
    payer_name = user_data["payer_name"]
    participants_map = user_data["participants_map"]
    reverse = {pid: name for name, pid in participants_map.items()}
    payee_names = [reverse[pid] for pid in payee_ids]

    key = f"{user_id}_{message_id}"
    pending[key] = PendingExpense(
        title=title,
        amount_cents=int(amount * 100),
        payer_id=payer_id,
        paid_for=[(pid, 1) for pid in payee_ids],
        tg_name=tg_name,
        group_id=group_id,
    )

    return format_confirmation(title, amount, payer_name, payee_names), confirm_keyboard(key)


def _reset_add_state(user_data: dict) -> None:
    for key in (
        "expense_title",
        "expense_amount",
        "payer_id",
        "payer_name",
        "selected_payees",
        "participants_map",
    ):
        user_data.pop(key, None)


async def _notify_admin_llm_error(
    context: ContextTypes.DEFAULT_TYPE,
    user: Any,
    raw_text: str,
    error: str,
    raw_response: str | None,
) -> None:
    if not ADMIN_TELEGRAM_USER_ID:
        return
    try:
        user_info = f"@{user.username}" if user.username else f"ID: {user.id}"
        await context.bot.send_message(
            chat_id=ADMIN_TELEGRAM_USER_ID,
            text=(
                f"⚠️ <b>LLM Parsing failed</b> for {html.escape(user_info)}\n\n"
                f"<b>Input:</b> <code>{html.escape(str(raw_text))}</code>\n"
                f"<b>Error:</b> {html.escape(str(error))}\n"
                f"<b>Raw Response:</b>\n<pre>{html.escape(str(raw_response))}</pre>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to send error report to admin: {e}")
