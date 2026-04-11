"""Inline callback-query button dispatcher."""

from __future__ import annotations

import html
import logging

from telegram import Message, Update
from telegram.ext import ContextTypes

from config import (
    get_spliit,
    pending,
    pending_deletes,
    pending_settlements,
)
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
from domain import id_to_name_map
from helpers import is_dm
from services import (
    create_expense,
    delete_expense,
    settle_reimbursement,
)

from .common import _group_name, build_mention, reply_to_callback

logger = logging.getLogger(__name__)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query
    await query.answer()

    data: str = query.data or ""
    if data.startswith(CB_CONFIRM):
        key = data[len(CB_CONFIRM) :]
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
        expense_title = f"[telebot-{tg_name}] {title}"
        try:
            create_expense(
                group_id=group_id,
                title=expense_title,
                paid_by=paid_by_id,
                paid_for=paid_for,
                amount=amount,
            )
            if query.message:
                await query.edit_message_reply_markup(reply_markup=None)

            client = get_spliit(group_id)
            id_name, currency = id_to_name_map(client)
            payer_name = id_name.get(paid_by_id, "Unknown")
            payee_names = [id_name.get(pid, "Unknown") for pid, _ in paid_for]

            involved = {*payee_names, payer_name}
            mentions = [await build_mention(n, context) for n in involved]

            amount_display = amount / 100
            share = amount_display / len(payee_names)
            msg = (
                f"💸 <b>{html.escape(title)}</b> added\n"
                f"Amount: {format_money(amount, currency)}\n"
                f"Paid by: {html.escape(payer_name)}\n"
                f"Split ({html.escape(currency)}{share:.2f} each): "
                f"{html.escape(', '.join(payee_names))}\n\n"
                f"👋 {' '.join(mentions)}"
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

    elif data.startswith(CB_CANCEL):
        key = data[len(CB_CANCEL) :]
        pending.pop(key, None)
        await reply_to_callback(query, "Cancelled.")

    elif data.startswith(CB_DEL_CONFIRM):
        key = data[len(CB_DEL_CONFIRM) :]
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

    elif data.startswith(CB_DEL_CANCEL):
        key = data[len(CB_DEL_CANCEL) :]
        pending_deletes.pop(key, None)
        await reply_to_callback(query, "Cancelled.")

    elif data.startswith(CB_SETTLE):
        key = data[len(CB_SETTLE) :]
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
            id_name, currency = id_to_name_map(client)
            from_name = id_name.get(from_id, from_id)
            to_name = id_name.get(to_id, to_id)
            await reply_to_callback(
                query,
                f"Marked as paid: {from_name} -> {to_name} ({format_money(amount, currency)})",
            )
        except Exception as e:
            logger.error(f"Failed to settle reimbursement: {e}")
            await reply_to_callback(query, f"Failed: {e}")

    elif data.startswith(CB_SETTLE_CANCEL):
        key_prefix = data[len(CB_SETTLE_CANCEL) :]
        for key in list(pending_settlements):
            if key.startswith(f"{key_prefix}_"):
                pending_settlements.pop(key, None)
        await reply_to_callback(query, "Cancelled.")

    elif data.startswith(CB_SELECT_GROUP):
        if not is_dm(update):
            await reply_to_callback(query, "Use /switch in a DM.")
            return
        group_id = data[len(CB_SELECT_GROUP) :]
        assert context.user_data is not None
        context.user_data["active_group"] = group_id
        client = get_spliit(group_id)
        await reply_to_callback(query, f"Switched to: {_group_name(client, group_id)}")
