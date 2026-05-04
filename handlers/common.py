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
    SplitMode,
)
from expense_draft import clear_draft, get_draft
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
    group_id: str,
    split_mode: SplitMode = SplitMode.EVENLY,
    paid_for: list[tuple[str, int]] | None = None,
    currency: str = "",
) -> tuple[str, InlineKeyboardMarkup]:
    """Build confirmation for a pending expense and store it.

    For ``EVENLY`` mode the draft's payee ids are sufficient. For other modes
    pass ``paid_for`` with share semantics matching ``split_mode``.
    """
    draft = get_draft(user_data)
    assert draft.title is not None
    assert draft.amount is not None
    assert draft.payer_name is not None
    reverse = draft.id_to_name()
    payee_names = draft.payee_names()

    if paid_for is None:
        paid_for = [(pid, 1) for pid in draft.payee_ids]

    key = f"{user_id}_{message_id}"
    pending[key] = draft.to_pending_expense(
        tg_name=tg_name,
        group_id=group_id,
        split_mode=split_mode,
        paid_for=paid_for,
    )

    paid_for_named = [(reverse[pid], share) for pid, share in paid_for]
    return (
        format_confirmation(
            draft.title,
            draft.amount,
            draft.payer_name,
            payee_names,
            split_mode=split_mode,
            paid_for_named=paid_for_named,
            currency=currency,
        ),
        confirm_keyboard(key),
    )


def _reset_add_state(user_data: dict) -> None:
    clear_draft(user_data)


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
