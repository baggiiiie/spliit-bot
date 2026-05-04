"""Inline callback-query button dispatcher."""

from __future__ import annotations

import logging

from telegram import CallbackQuery, Message, Update
from telegram.ext import ContextTypes

from callback_responses import reply_to_callback
from config import get_spliit
from constants import (
    CB_CANCEL,
    CB_CONFIRM,
    CB_DEL_CANCEL,
    CB_DEL_CONFIRM,
    CB_SELECT_GROUP,
    CB_SETTLE,
    CB_SETTLE_CANCEL,
    format_money,
)
from domain import participant_directory
from expense_receipt import format_expense_receipt, involved_names
from group_selection import group_name
from helpers import is_dm
from pending_store import pending, pending_deletes, pending_settlements
from services import (
    create_expense,
    delete_expense,
    settle_reimbursement,
)
from telegram_mentions import build_mention
from user_session import set_active_group

logger = logging.getLogger(__name__)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query
    await query.answer()

    data: str = query.data or ""
    if data.startswith(CB_CONFIRM):
        await _confirm_expense(query, context, data[len(CB_CONFIRM) :])
    elif data.startswith(CB_CANCEL):
        await _cancel_expense(query, data[len(CB_CANCEL) :])
    elif data.startswith(CB_DEL_CONFIRM):
        await _confirm_delete(query, data[len(CB_DEL_CONFIRM) :])
    elif data.startswith(CB_DEL_CANCEL):
        await _cancel_delete(query, data[len(CB_DEL_CANCEL) :])
    elif data.startswith(CB_SETTLE):
        await _confirm_settlement(query, data[len(CB_SETTLE) :])
    elif data.startswith(CB_SETTLE_CANCEL):
        await _cancel_settlements(query, data[len(CB_SETTLE_CANCEL) :])
    elif data.startswith(CB_SELECT_GROUP):
        await _select_group(update, context, query, data[len(CB_SELECT_GROUP) :])


async def _confirm_expense(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    key: str,
) -> None:
    info = pending.pop(key, None)
    if not info:
        await reply_to_callback(query, "Expired. Try again.")
        return

    title = info.title
    amount = info.amount_cents
    paid_by_id = info.payer_id
    paid_for = info.paid_for
    tg_name = info.tg_name
    group_id = info.group_id
    split_mode = info.split_mode
    expense_title = f"[telebot-{tg_name}] {title}"
    try:
        create_expense(
            group_id=group_id,
            title=expense_title,
            paid_by=paid_by_id,
            paid_for=paid_for,
            amount=amount,
            split_mode=split_mode,
        )
        if query.message:
            await query.edit_message_reply_markup(reply_markup=None)

        client = get_spliit(group_id)
        directory = participant_directory(client)
        mentions = [
            await build_mention(name, context)
            for name in involved_names(paid_by_id, paid_for, directory)
        ]
        msg = format_expense_receipt(
            title=title,
            amount_cents=amount,
            payer_id=paid_by_id,
            paid_for=paid_for,
            split_mode=split_mode,
            directory=directory,
            mentions=mentions,
        )
        assert isinstance(query.message, Message)
        await query.message.reply_text(
            msg,
            parse_mode="HTML",
            reply_to_message_id=query.message.message_id,
        )
    except Exception as e:
        logger.error(f"Failed to add expense: {e}")
        await reply_to_callback(query, f"Failed: {e}")


async def _cancel_expense(query: CallbackQuery, key: str) -> None:
    pending.pop(key, None)
    await reply_to_callback(query, "Cancelled.")


async def _confirm_delete(query: CallbackQuery, key: str) -> None:
    pending_delete = pending_deletes.pop(key, None)
    if not pending_delete:
        await reply_to_callback(query, "Expired. Try again.")
        return
    expense_id, group_id = pending_delete.expense_id, pending_delete.group_id
    try:
        delete_expense(group_id, expense_id)
        await reply_to_callback(query, "Deleted.")
    except Exception as e:
        logger.error(f"Failed to delete expense: {e}")
        await reply_to_callback(query, f"Failed: {e}")


async def _cancel_delete(query: CallbackQuery, key: str) -> None:
    pending_deletes.pop(key, None)
    await reply_to_callback(query, "Cancelled.")


async def _confirm_settlement(query: CallbackQuery, key: str) -> None:
    reimbursement = pending_settlements.pop(key, None)
    if not reimbursement:
        await reply_to_callback(query, "Expired. Try again.")
        return

    from_id = reimbursement.from_id
    to_id = reimbursement.to_id
    amount = reimbursement.amount
    group_id = reimbursement.group_id
    try:
        client = get_spliit(group_id)
        settle_reimbursement(group_id, from_id, to_id, amount)
        directory = participant_directory(client)
        from_name = directory.participant_name(from_id)
        to_name = directory.participant_name(to_id)
        await reply_to_callback(
            query,
            f"Marked as paid: {from_name} -> {to_name} "
            f"({format_money(amount, directory.currency)})",
        )
    except Exception as e:
        logger.error(f"Failed to settle reimbursement: {e}")
        await reply_to_callback(query, f"Failed: {e}")


async def _cancel_settlements(query: CallbackQuery, key_prefix: str) -> None:
    for key in list(pending_settlements):
        if key.startswith(f"{key_prefix}_"):
            pending_settlements.pop(key, None)
    await reply_to_callback(query, "Cancelled.")


async def _select_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: CallbackQuery,
    group_id: str,
) -> None:
    if not is_dm(update):
        await reply_to_callback(query, "Use /switch in a DM.")
        return
    assert context.user_data is not None
    set_active_group(context.user_data, group_id)
    client = get_spliit(group_id)
    await reply_to_callback(query, f"Switched to: {group_name(client, group_id)}")
