"""Telegram bot command and callback handlers."""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

import httpx
from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import (
    ADMIN_TELEGRAM_USER_ID,
    AMOUNT,
    PAYEES,
    PAYER,
    SPLIIT_GROUP_ID,
    TITLE,
    PaidFor,
    pending,
    pending_deletes,
    spliit,
)
from helpers import (
    build_mention,
    confirm_keyboard,
    format_confirmation,
    id_to_name_map,
    is_allowed_chat,
    participant_keyboard,
    tg_display_name,
)
from parsing import parse_add_command, parse_with_llm

logger = logging.getLogger(__name__)


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


def get_balances(group_id: str) -> dict[str, Any]:
    params_input = {"0": {"json": {"groupId": group_id}}}
    params = {"batch": "1", "input": json.dumps(params_input)}
    response = httpx.get("https://spliit.app/api/trpc/groups.balances.list", params=params)
    return response.json()[0]["result"]["data"]["json"]


def get_expenses(group_id: str) -> list[dict[str, Any]]:
    params_input = {
        "0": {"json": {"groupId": group_id}},
        "1": {"json": {"groupId": group_id}},
    }
    params = {"batch": "1", "input": json.dumps(params_input)}
    response = httpx.get("https://spliit.app/api/trpc/groups.get,groups.getDetails", params=params)
    data = response.json()
    return data[1]["result"]["data"]["json"]["expenses"]


def delete_expense(group_id: str, expense_id: str) -> None:
    params = {"batch": "1"}
    json_data = {
        "0": {
            "json": {
                "groupId": group_id,
                "expenseId": expense_id,
            },
        },
    }
    response = httpx.post(
        "https://spliit.app/api/trpc/groups.expenses.delete",
        params=params,
        json=json_data,
    )
    response.raise_for_status()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    await update.message.reply_text(
        "baggiiiie's Spliit Bot\n\n"
        "url: https://spliit.app/groups/WF\_-cIdW0KrDhsIal1uhI/\n"
        "Commands:\n"
        "/group - Show participants\n"
        "/balance - Show balances\n"
        "/add title, amount, with participants\n"
        "/dellast - Delete the latest expense\n\n"
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
    if not spliit:
        await update.message.reply_text(
            "SPLIIT_GROUP_ID not configured.",
            reply_to_message_id=update.message.message_id,
        )
        return

    try:
        id_name, currency = id_to_name_map(spliit)
        balance_data = get_balances(SPLIIT_GROUP_ID)
        balances = balance_data["balances"]
        reimbursements = balance_data["reimbursements"]

        group = spliit.get_group()
        lines = [f"**{group['name']}** Balances\n"]
        for pid, data in balances.items():
            name = id_name.get(pid, pid)
            total = data["total"] / 100
            if total > 0:
                lines.append(f"- {name}: +{currency}{total:.2f}")
            elif total < 0:
                lines.append(f"- {name}: {currency}{total:.2f}")
            else:
                lines.append(f"- {name}: {currency}0.00")

        if reimbursements:
            lines.append("\n**Suggested Payments:**")
            for r in reimbursements:
                from_name = id_name.get(r["from"], r["from"])
                to_name = id_name.get(r["to"], r["to"])
                amount = r["amount"] / 100
                lines.append(f"- {from_name} -> {to_name}: {currency}{amount:.2f}")

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


async def dellast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    if not spliit:
        await update.message.reply_text(
            "SPLIIT_GROUP_ID not configured.",
            reply_to_message_id=update.message.message_id,
        )
        return

    try:
        expenses = get_expenses(SPLIIT_GROUP_ID)
        if not expenses:
            await update.message.reply_text(
                "No expenses found.",
                reply_to_message_id=update.message.message_id,
            )
            return

        latest = expenses[0]
        expense_id = latest["id"]
        title = latest["title"]
        amount = latest["amount"] / 100

        id_name, currency = id_to_name_map(spliit)
        payer_name = id_name.get(latest["paidById"], "Unknown")
        payee_names = [id_name.get(p["participantId"], "Unknown") for p in latest["paidFor"]]

        assert update.effective_user
        key = f"{update.effective_user.id}_{update.message.message_id}"
        pending_deletes[key] = expense_id

        await update.message.reply_text(
            f"Delete latest expense?\n\n"
            f"**{title}**\n"
            f"Amount: {currency}{amount:.2f}\n"
            f"Paid by: {payer_name}\n"
            f"Split: {', '.join(payee_names)}",
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Delete", callback_data=f"delyes_{key}"),
                        InlineKeyboardButton("Cancel", callback_data=f"delno_{key}"),
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
    if not spliit:
        await update.message.reply_text(
            "SPLIIT_GROUP_ID not configured.",
            reply_to_message_id=update.message.message_id,
        )
        return

    try:
        group = spliit.get_group()
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


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not is_allowed_chat(update) or not update.message or not update.effective_user:
        return ConversationHandler.END
    if not spliit:
        await update.message.reply_text(
            "SPLIIT_GROUP_ID not configured.",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    text = (update.message.text or "").strip()

    if text == "/add":
        await update.message.reply_text(
            "Enter expense title:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. Dinner"),
            reply_to_message_id=update.message.message_id,
        )
        return TITLE

    assert context.user_data is not None

    try:
        participants_map = spliit.get_participants()
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    context.user_data["participants_map"] = participants_map
    participant_names = list(participants_map.keys())

    expense = parse_add_command(text, participant_names)

    if not expense:
        raw_text = re.sub(r"^/add[-_]?bill?\s*", "", text, flags=re.IGNORECASE).strip()
        has_number = bool(re.search(r"\d", raw_text))
        has_participant = any(n.lower() in raw_text.lower() for n in participant_names)
        if not has_number and not has_participant:
            await update.message.reply_text(
                "Format: `/add title, amount, names`",
                parse_mode="Markdown",
                reply_to_message_id=update.message.message_id,
            )
            return ConversationHandler.END
        llm_result, raw_response = parse_with_llm(raw_text, participant_names)
        if isinstance(llm_result, str):
            if ADMIN_TELEGRAM_USER_ID:
                try:
                    user_info = f"@{update.effective_user.username}" if update.effective_user.username else f"ID: {update.effective_user.id}"
                    await context.bot.send_message(
                        chat_id=ADMIN_TELEGRAM_USER_ID,
                        text=(
                            f"⚠️ <b>LLM Parsing failed</b> for {html.escape(user_info)}\n\n"
                            f"<b>Input:</b> <code>{html.escape(str(raw_text))}</code>\n"
                            f"<b>Error:</b> {html.escape(str(llm_result))}\n"
                            f"<b>Raw Response:</b>\n<pre>{html.escape(str(raw_response))}</pre>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"Failed to send error report to admin: {e}")

            await update.message.reply_text(
                llm_result,
                parse_mode="Markdown",
                reply_to_message_id=update.message.message_id,
            )
            return ConversationHandler.END
        if llm_result:
            expense = llm_result
            logger.info(f"LLM parsed: {expense}")

    if not expense:
        await update.message.reply_text(
            "Format: `/add title, amount, names`",
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    if expense.title:
        context.user_data["expense_title"] = expense.title
    if expense.amount:
        context.user_data["expense_amount"] = expense.amount
    if expense.payer:
        context.user_data["payer_id"] = participants_map[expense.payer]
        context.user_data["payer_name"] = expense.payer
    if expense.participants:
        name_map = {n.lower(): (n, pid) for n, pid in participants_map.items()}
        matched = [
            (n, pid)
            for n, pid in ((name, name_map.get(name)) for name in expense.participants)
            if pid
        ]
        context.user_data["selected_payees"] = [pid for _, (_, pid) in matched]

    # Flow Control: Find first missing field
    if not context.user_data.get("expense_title"):
        await update.message.reply_text(
            "Enter expense title:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. Dinner"),
            reply_to_message_id=update.message.message_id,
        )
        return TITLE

    if not context.user_data.get("expense_amount"):
        await update.message.reply_text(
            f"*{context.user_data['expense_title']}*\nEnter amount:",
            parse_mode="Markdown",
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
            reply_to_message_id=update.message.message_id,
        )
        return AMOUNT

    if not context.user_data.get("payer_id"):
        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        await update.message.reply_text(
            f"*{title}* — {amount:.2f}\n\nWho paid?",
            parse_mode="Markdown",
            reply_markup=participant_keyboard(participants_map, "payer_"),
            reply_to_message_id=update.message.message_id,
        )
        return PAYER

    if not context.user_data.get("selected_payees"):
        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        payer_name = context.user_data["payer_name"]
        await update.message.reply_text(
            f"*{title}* — {amount:.2f}\nPaid by: {payer_name}\n\nSelect who to split with:",
            parse_mode="Markdown",
            reply_markup=participant_keyboard(
                participants_map, "payee_", done_btn=("< Done >", "payee_done")
            ),
            reply_to_message_id=update.message.message_id,
        )
        return PAYEES

    # If everything is already present
    title = context.user_data["expense_title"]
    amount = context.user_data["expense_amount"]
    payer_id = context.user_data["payer_id"]
    payer_name = context.user_data["payer_name"]
    selected_payees = context.user_data["selected_payees"]
    reverse = {pid: name for name, pid in participants_map.items()}
    payee_names = [reverse[pid] for pid in selected_payees]
    paid_for: PaidFor = [(pid, 1) for pid in selected_payees]

    key = f"{update.effective_user.id}_{update.message.message_id}"
    pending[key] = (title, int(amount * 100), payer_id, paid_for, tg_display_name(update))

    await update.message.reply_text(
        format_confirmation(title, amount, payer_name, payee_names),
        parse_mode="Markdown",
        reply_markup=confirm_keyboard(key),
    )
    return ConversationHandler.END


async def interactive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text and context.user_data is not None
    context.user_data["expense_title"] = update.message.text.strip()
    await update.message.reply_text(
        "Enter amount:",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
        reply_to_message_id=update.message.message_id,
    )
    return AMOUNT


async def interactive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text and context.user_data is not None
    text = update.message.text.strip()
    match = re.match(r"(\d+(?:\.\d+)?)", text)
    if not match:
        await update.message.reply_text(
            "Invalid amount. Enter a number:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
            reply_to_message_id=update.message.message_id,
        )
        return AMOUNT

    context.user_data["expense_amount"] = float(match.group(1))

    assert spliit
    try:
        participants_map = spliit.get_participants()
        context.user_data["participants_map"] = participants_map
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Who paid?",
        reply_markup=participant_keyboard(participants_map, "payer_"),
        reply_to_message_id=update.message.message_id,
    )
    return PAYER


async def interactive_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and context.user_data is not None
    await query.answer()

    payer_id = query.data[6:]
    participants_map = context.user_data["participants_map"]
    reverse = {pid: name for name, pid in participants_map.items()}

    context.user_data["payer_id"] = payer_id
    context.user_data["payer_name"] = reverse[payer_id]

    pre_selected = context.user_data.get("selected_payees", [])
    if pre_selected:
        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        paid_for: PaidFor = [(pid, 1) for pid in pre_selected]
        payee_names = [reverse[pid] for pid in pre_selected]

        assert query.message and update.effective_user
        key = f"{update.effective_user.id}_{query.message.message_id}"
        pending[key] = (title, int(amount * 100), payer_id, paid_for, tg_display_name(update))

        await query.edit_message_text(
            format_confirmation(title, amount, reverse[payer_id], payee_names),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard(key),
        )
        return ConversationHandler.END

    context.user_data["selected_payees"] = []
    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=participant_keyboard(
            participants_map, "payee_", done_btn=("< Done >", "payee_done")
        ),
    )
    return PAYEES


async def interactive_payees(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and update.effective_user and context.user_data is not None
    await query.answer()

    data: str = query.data
    if data == "payee_done":
        selected: list[str] = context.user_data.get("selected_payees", [])
        if not selected:
            await query.answer("Select at least one person", show_alert=True)
            return PAYEES

        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        payer_id = context.user_data["payer_id"]
        payer_name = context.user_data["payer_name"]
        participants_map = context.user_data["participants_map"]
        reverse = {pid: name for name, pid in participants_map.items()}

        paid_for: PaidFor = [(pid, 1) for pid in selected]
        payee_names = [reverse[pid] for pid in selected]

        assert query.message
        key = f"{update.effective_user.id}_{query.message.message_id}"
        pending[key] = (title, int(amount * 100), payer_id, paid_for, tg_display_name(update))

        await query.edit_message_text(
            format_confirmation(title, amount, payer_name, payee_names),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard(key),
        )
        return ConversationHandler.END

    payee_id = data[6:]
    participants_map = context.user_data["participants_map"]
    selected = context.user_data.get("selected_payees", [])
    if payee_id == "all":
        all_ids = list(participants_map.values())
        selected = [] if set(selected) == set(all_ids) else list(all_ids)
    elif payee_id in selected:
        selected.remove(payee_id)
    else:
        selected.append(payee_id)
    context.user_data["selected_payees"] = selected
    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=participant_keyboard(
            participants_map, "payee_", set(selected), done_btn=("✓ Done", "payee_done")
        ),
    )
    return PAYEES


async def cancel_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message
    await update.message.reply_text(
        "Cancelled.",
        reply_to_message_id=update.message.message_id,
    )
    return ConversationHandler.END


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query
    await query.answer()

    data: str = query.data or ""
    if data.startswith("yes_"):
        key = data[4:]
        info = pending.pop(key, None)
        if not info:
            await reply_to_callback(query, "Expired. Try again.")
            return

        title, amount, paid_by_id, paid_for, tg_name = info
        expense_title = f"[telebot-{tg_name}] {title}"
        try:
            assert spliit
            spliit.add_expense(
                title=expense_title,
                paid_by=paid_by_id,
                paid_for=paid_for,
                amount=amount,
            )
            if query.message:
                await query.edit_message_reply_markup(reply_markup=None)

            id_name, currency = id_to_name_map(spliit)
            payer_name = id_name.get(paid_by_id, "Unknown")
            payee_names = [id_name.get(pid, "Unknown") for pid, _ in paid_for]

            involved = set([*payee_names, payer_name])
            mentions = [await build_mention(n, context) for n in involved]

            amount_display = amount / 100
            share = amount_display / len(payee_names)
            msg = (
                f"💸 <b>{html.escape(title)}</b> added\n"
                f"Amount: {html.escape(currency)}{amount_display:.2f}\n"
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

    elif data.startswith("no_"):
        key = data[3:]
        pending.pop(key, None)
        await reply_to_callback(query, "Cancelled.")

    elif data.startswith("delyes_"):
        key = data[7:]
        expense_id = pending_deletes.pop(key, None)
        if not expense_id:
            await reply_to_callback(query, "Expired. Try again.")
            return
        try:
            delete_expense(SPLIIT_GROUP_ID, expense_id)
            await reply_to_callback(query, "Deleted.")
        except Exception as e:
            logger.error(f"Failed to delete expense: {e}")
            await reply_to_callback(query, f"Failed: {e}")

    elif data.startswith("delno_"):
        key = data[6:]
        pending_deletes.pop(key, None)
        await reply_to_callback(query, "Cancelled.")
