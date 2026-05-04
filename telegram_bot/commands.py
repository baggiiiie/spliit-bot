"""Simple Telegram command handlers (no conversation state)."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from domain import format_activity_line_html, undoable_activity
from spliit_integration.gateway import gateway
from telegram_bot.access import is_allowed_chat, is_dm
from telegram_bot.constants import CB_DEL_CANCEL, CB_DEL_CONFIRM, CB_SETTLE, CB_SETTLE_CANCEL
from telegram_bot.group_picker import configured_group_ids, group_picker_options, require_group
from telegram_bot.keyboards import group_picker_keyboard, reimbursement_keyboard
from telegram_bot.session import PendingDelete, PendingSettlement, Session
from telegram_bot.ui import (
    format_balance_lines,
    format_settlement_line,
    format_settlement_option_label,
)

logger = logging.getLogger(__name__)


def parse_positive_count_arg(context: ContextTypes.DEFAULT_TYPE, default: int) -> int | str:
    if not context.args:
        return default
    try:
        count = int(context.args[0])
    except ValueError:
        return "Count must be a positive integer."
    if count < 1:
        return "Count must be a positive integer."
    return count


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
    group_id = await require_group(update, context.user_data, update.message)
    if not group_id:
        return

    try:
        group = gateway.group(group_id)
        directory = group.directory
        balance_report = gateway.balances(group_id)
        lines = format_balance_lines(
            group.name, balance_report.balances, balance_report.reimbursements, directory
        )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id,
        )
    except Exception as e:
        logger.error("Failed to get balances: %s", e)
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def latest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    group_id = await require_group(update, context.user_data, update.message)
    if not group_id:
        return

    try:
        count = parse_positive_count_arg(context, 5)
        if isinstance(count, str):
            await update.message.reply_text(
                count,
                reply_to_message_id=update.message.message_id,
            )
            return

        activities = gateway.activities(group_id, count)
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
        logger.error("Failed to get latest expenses: %s", e)
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def settle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message or not update.effective_user:
        return
    group_id = await require_group(update, context.user_data, update.message)
    if not group_id:
        return

    try:
        directory = gateway.group(group_id).directory
        balance_report = gateway.balances(group_id)
        reimbursements = balance_report.reimbursements
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
            settlement_key = f"{key_prefix}_{index}"
            Session(context.user_data, context.bot_data).stash(
                settlement_key,
                PendingSettlement(
                    from_id=reimbursement.from_id,
                    to_id=reimbursement.to_id,
                    amount=reimbursement.amount_cents,
                    group_id=group_id,
                ),
            )
            lines.append(format_settlement_line(index + 1, reimbursement, directory))
            options.append(
                (
                    format_settlement_option_label(reimbursement, directory),
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
        logger.error("Failed to get suggested reimbursements: %s", e)
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def undo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    group_id = await require_group(update, context.user_data, update.message)
    if not group_id:
        return

    try:
        count = parse_positive_count_arg(context, 1)
        if isinstance(count, str):
            await update.message.reply_text(
                count,
                reply_to_message_id=update.message.message_id,
            )
            return

        activities = gateway.activities(group_id, count)
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
        Session(context.user_data, context.bot_data).stash(
            key, PendingDelete(expense_id=expense_id, group_id=group_id)
        )

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
        logger.error("Failed to get latest expense: %s", e)
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )


async def group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    group_id = await require_group(update, context.user_data, update.message)
    if not group_id:
        return

    try:
        group = gateway.group(group_id)
        names = [participant.name for participant in group.directory.participants]
        await update.message.reply_text(
            f"**{group.name}** ({group.currency})\n\nParticipants:\n"
            + "\n".join(f"- {n}" for n in names),
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id,
        )
    except Exception as e:
        logger.error("Failed to get group: %s", e)
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
    if not configured_group_ids():
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
