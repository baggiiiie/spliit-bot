"""Inline callback-query button dispatcher."""

from __future__ import annotations

import logging

from telegram import CallbackQuery, Message, Update
from telegram.ext import ContextTypes

from domain import format_money
from spliit_integration.gateway import NewExpense, Settlement, gateway
from telegram_bot.access import is_dm
from telegram_bot.constants import (
    CB_CANCEL,
    CB_CONFIRM,
    CB_DEL_CANCEL,
    CB_DEL_CONFIRM,
    CB_SELECT_GROUP,
    CB_SETTLE,
    CB_SETTLE_CANCEL,
)
from telegram_bot.group_picker import group_name
from telegram_bot.session import (
    PendingDelete,
    PendingExpense,
    PendingSettlement,
    Session,
    set_active_group,
)
from telegram_bot.ui import (
    build_mention,
    format_expense_receipt,
    involved_names,
    reply_to_callback,
)

logger = logging.getLogger(__name__)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query
    await query.answer()

    data: str = query.data or ""
    if data.startswith(CB_CONFIRM):
        await _confirm_expense(query, context, data[len(CB_CONFIRM) :])
    elif data.startswith(CB_CANCEL):
        await _cancel_expense(query, context, data[len(CB_CANCEL) :])
    elif data.startswith(CB_DEL_CONFIRM):
        await _confirm_delete(query, context, data[len(CB_DEL_CONFIRM) :])
    elif data.startswith(CB_DEL_CANCEL):
        await _cancel_delete(query, context, data[len(CB_DEL_CANCEL) :])
    elif data.startswith(CB_SETTLE):
        await _confirm_settlement(query, context, data[len(CB_SETTLE) :])
    elif data.startswith(CB_SETTLE_CANCEL):
        await _cancel_settlements(query, context, data[len(CB_SETTLE_CANCEL) :])
    elif data.startswith(CB_SELECT_GROUP):
        await _select_group(update, context, query, data[len(CB_SELECT_GROUP) :])


async def _confirm_expense(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    key: str,
) -> None:
    info = Session(context.user_data, context.bot_data).pop(key)
    if not isinstance(info, PendingExpense):
        await reply_to_callback(query, "Expired. Try again.")
        return

    expense = info.expense
    title = expense.title
    amount = expense.amount_cents
    paid_by_id = expense.payer_id
    paid_for = expense.paid_for
    tg_name = info.tg_name
    group_id = info.group_id
    split_mode = expense.split_mode
    expense_title = f"[telebot-{tg_name}] {title}"
    try:
        gateway.create_expense(
            group_id,
            NewExpense(
                title=expense_title,
                paid_by=paid_by_id,
                paid_for=paid_for,
                amount_cents=amount,
                split_mode=split_mode,
            ),
        )
        if query.message:
            await query.edit_message_reply_markup(reply_markup=None)

        directory = gateway.group(group_id).directory
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
        logger.error("Failed to add expense: %s", e)
        await reply_to_callback(query, f"Failed: {e}")


async def _cancel_expense(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, key: str
) -> None:
    Session(context.user_data, context.bot_data).pop(key)
    await reply_to_callback(query, "Cancelled.")


async def _confirm_delete(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, key: str
) -> None:
    pending_delete = Session(context.user_data, context.bot_data).pop(key)
    if not isinstance(pending_delete, PendingDelete):
        await reply_to_callback(query, "Expired. Try again.")
        return
    expense_id, group_id = pending_delete.expense_id, pending_delete.group_id
    try:
        gateway.delete_expense(group_id, expense_id)
        await reply_to_callback(query, "Deleted.")
    except Exception as e:
        logger.error("Failed to delete expense: %s", e)
        await reply_to_callback(query, f"Failed: {e}")


async def _cancel_delete(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, key: str
) -> None:
    Session(context.user_data, context.bot_data).pop(key)
    await reply_to_callback(query, "Cancelled.")


async def _confirm_settlement(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, key: str
) -> None:
    reimbursement = Session(context.user_data, context.bot_data).pop(key)
    if not isinstance(reimbursement, PendingSettlement):
        await reply_to_callback(query, "Expired. Try again.")
        return

    from_id = reimbursement.from_id
    to_id = reimbursement.to_id
    amount = reimbursement.amount
    group_id = reimbursement.group_id
    try:
        gateway.settle(
            group_id,
            Settlement(from_id=from_id, to_id=to_id, amount_cents=amount),
        )
        directory = gateway.group(group_id).directory
        from_name = directory.participant_name(from_id)
        to_name = directory.participant_name(to_id)
        await reply_to_callback(
            query,
            f"Marked as paid: {from_name} -> {to_name} "
            f"({format_money(amount, directory.currency)})",
        )
    except Exception as e:
        logger.error("Failed to settle reimbursement: %s", e)
        await reply_to_callback(query, f"Failed: {e}")


async def _cancel_settlements(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, key_prefix: str
) -> None:
    Session(context.user_data, context.bot_data).cancel_with_prefix(f"{key_prefix}_")
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
    await reply_to_callback(query, f"Switched to: {group_name(group_id)}")
