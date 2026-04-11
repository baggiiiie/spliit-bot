"""Simple Telegram command handlers (no conversation state)."""

from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import (
    ALL_GROUP_IDS,
    pending_deletes,
    pending_settlements,
)
from constants import (
    CB_DEL_CANCEL,
    CB_DEL_CONFIRM,
    CB_SETTLE,
    CB_SETTLE_CANCEL,
    PendingDelete,
    PendingSettlement,
    format_money,
)
from domain import (
    format_activity_line_html,
    group_picker_options,
    id_to_name_map,
    undoable_activity,
)
from helpers import (
    group_picker_keyboard,
    is_allowed_chat,
    is_dm,
    reimbursement_keyboard,
)
from services import (
    get_activities,
    get_balances,
)

from .common import _parse_count_arg, _require_group

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    await update.message.reply_text(
        "baggiiiie's Spliit Bot\n\n"
        "Commands:\n"
        "/group - Show participants\n"
        "/balance - Show balances\n"
        "/settle - Mark a suggested reimbursement as paid\n"
        "/add title, amount, with participants\n"
        "/latest [n] - Show latest activities (default 5)\n"
        "/undo [n] - Undo activity #n if reversible (default 1)\n"
        "/switch - Select which Spliit group to manage (DM)\n\n"
        "Example:\n"
        "`/add` (interactive)\n"
        "`/add $title, $amount` (interactive)\n"
        "`/add $title, $amount, baggie neo yoga ricky`\n"
        "↳ bot will ask who paid",
        parse_mode="Markdown",
        reply_to_message_id=update.message.message_id,
    )


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    resolved = await _require_group(update, context.user_data, update.message)
    if not resolved:
        return
    group_id, client = resolved

    try:
        id_name, currency = id_to_name_map(client)
        balance_data = get_balances(group_id)
        balances = balance_data["balances"]
        reimbursements = balance_data["reimbursements"]

        group = client.get_group()
        lines = [f"**{group['name']}** Balances\n"]
        for pid, data in balances.items():
            name = id_name.get(pid, pid)
            total = data["total"]
            sign = "+" if total > 0 else ""
            lines.append(f"- {name}: {sign}{format_money(total, currency)}")

        if reimbursements:
            lines.append("\n**Suggested Payments:**")
            for r in reimbursements:
                from_name = id_name.get(r["from"], r["from"])
                to_name = id_name.get(r["to"], r["to"])
                lines.append(f"- {from_name} -> {to_name}: {format_money(r['amount'], currency)}")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id,
        )
    except Exception as e:
        logger.error(f"Failed to get balances: {e}")
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def latest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    resolved = await _require_group(update, context.user_data, update.message)
    if not resolved:
        return
    group_id, _client = resolved

    try:
        count = _parse_count_arg(context, 5)
        if isinstance(count, str):
            await update.message.reply_text(
                count,
                reply_to_message_id=update.message.message_id,
            )
            return

        activities = get_activities(group_id, count)
        if not activities:
            await update.message.reply_text(
                "No activity found.",
                reply_to_message_id=update.message.message_id,
            )
            return

        lines = [f"<b>Latest {len(activities)} activities</b>\n"]
        for index, activity in enumerate(activities, start=1):
            lines.append(format_activity_line_html(activity, index))

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_to_message_id=update.message.message_id,
        )
    except Exception as e:
        logger.error(f"Failed to get latest expenses: {e}")
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def settle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message or not update.effective_user:
        return
    resolved = await _require_group(update, context.user_data, update.message)
    if not resolved:
        return
    group_id, client = resolved

    try:
        id_name, currency = id_to_name_map(client)
        balance_data = get_balances(group_id)
        reimbursements = balance_data["reimbursements"]
        if not reimbursements:
            await update.message.reply_text(
                "No suggested reimbursements.",
                reply_to_message_id=update.message.message_id,
            )
            return

        key_prefix = f"{update.effective_user.id}_{update.message.message_id}"
        lines = ["<b>Suggested reimbursements</b>\nSelect one to mark as paid:"]
        options: list[tuple[str, str]] = []
        for index, reimbursement in enumerate(reimbursements):
            from_id = reimbursement["from"]
            to_id = reimbursement["to"]
            amount = reimbursement["amount"]
            from_name = html.escape(id_name.get(from_id, from_id))
            to_name = html.escape(id_name.get(to_id, to_id))
            settlement_key = f"{key_prefix}_{index}"
            pending_settlements[settlement_key] = PendingSettlement(
                from_id=from_id, to_id=to_id, amount=amount, group_id=group_id
            )
            lines.append(
                f"{index + 1}. <b>{from_name}</b> owes <b>{to_name}</b> "
                f"{html.escape(format_money(amount, currency))}"
            )
            options.append(
                (
                    f"{id_name.get(from_id, from_id)} -> {id_name.get(to_id, to_id)} "
                    f"({format_money(amount, currency)})",
                    f"{CB_SETTLE}{settlement_key}",
                )
            )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_to_message_id=update.message.message_id,
            reply_markup=reimbursement_keyboard(
                options, cancel_btn=("Cancel", f"{CB_SETTLE_CANCEL}{key_prefix}")
            ),
        )
    except Exception as e:
        logger.error(f"Failed to get suggested reimbursements: {e}")
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def undo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    resolved = await _require_group(update, context.user_data, update.message)
    if not resolved:
        return
    group_id, _client = resolved

    try:
        count = _parse_count_arg(context, 1)
        if isinstance(count, str):
            await update.message.reply_text(
                count,
                reply_to_message_id=update.message.message_id,
            )
            return

        activities = get_activities(group_id, count)
        if not activities:
            await update.message.reply_text(
                "No activity found.",
                reply_to_message_id=update.message.message_id,
            )
            return

        if len(activities) < count:
            await update.message.reply_text(
                f"Only {len(activities)} activit{'y' if len(activities) == 1 else 'ies'} found.",
                reply_to_message_id=update.message.message_id,
            )
            return

        activity = activities[count - 1]
        undoable = undoable_activity(activity)
        if not undoable:
            await update.message.reply_text(
                "This activity can't be undone. Only newly created expenses can be undone.",
                reply_to_message_id=update.message.message_id,
            )
            return
        expense_id, _title = undoable

        assert update.effective_user
        key = f"{update.effective_user.id}_{update.message.message_id}"
        pending_deletes[key] = PendingDelete(expense_id=expense_id, group_id=group_id)

        await update.message.reply_text(
            f"Undo activity #{count}?\n\n{format_activity_line_html(activity, count)}",
            parse_mode="HTML",
            reply_to_message_id=update.message.message_id,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Delete", callback_data=f"{CB_DEL_CONFIRM}{key}"),
                        InlineKeyboardButton("Cancel", callback_data=f"{CB_DEL_CANCEL}{key}"),
                    ]
                ]
            ),
        )
    except Exception as e:
        logger.error(f"Failed to get latest expense: {e}")
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    resolved = await _require_group(update, context.user_data, update.message)
    if not resolved:
        return
    _group_id, client = resolved

    try:
        group = client.get_group()
        names = [p["name"] for p in group["participants"]]
        await update.message.reply_text(
            f"**{group['name']}** ({group['currency']})\n\nParticipants:\n"
            + "\n".join(f"- {n}" for n in names),
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id,
        )
    except Exception as e:
        logger.error(f"Failed to get group: {e}")
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def switch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    if not is_dm(update):
        await update.message.reply_text(
            "Use /switch in a DM.",
            reply_to_message_id=update.message.message_id,
        )
        return
    if not ALL_GROUP_IDS:
        await update.message.reply_text(
            "No groups configured.",
            reply_to_message_id=update.message.message_id,
        )
        return
    await update.message.reply_text(
        "Select a group:",
        reply_markup=group_picker_keyboard(group_picker_options()),
        reply_to_message_id=update.message.message_id,
    )
