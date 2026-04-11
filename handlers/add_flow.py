"""The /add conversation flow (multi-step expense creation)."""

from __future__ import annotations

import logging
import re
from typing import cast

from spliit import Spliit
from telegram import ForceReply, Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import (
    ALL_GROUP_IDS,
    get_spliit,
)
from constants import (
    AMOUNT,
    CB_PAYEE,
    CB_PAYEE_ALL,
    CB_PAYEE_DONE,
    CB_PAYER,
    CB_SELECT_GROUP,
    PAYEES,
    PAYER,
    SELECT_GROUP,
    TITLE,
)
from domain import group_picker_options
from helpers import (
    group_picker_keyboard,
    is_allowed_chat,
    is_dm,
    participant_keyboard,
    tg_display_name,
)
from parsing import parse_add_command, parse_with_llm

from .common import (
    FORMAT_HELP,
    NO_GROUP_MSG,
    _group_name,
    _notify_admin_llm_error,
    _reset_add_state,
    _store_pending_expense,
    resolve_group,
)

logger = logging.getLogger(__name__)


async def _continue_add_flow(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    tg_name: str,
    group_id: str,
    client: Spliit,
    text: str,
) -> int:
    if text == "/add":
        await message.reply_text(
            "Enter expense title:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. Dinner"),
            reply_to_message_id=message.message_id,
        )
        return TITLE

    assert context.user_data is not None

    try:
        participants_map = client.get_participants()
    except Exception as e:
        await message.reply_text(
            f"Error: {e}",
            reply_to_message_id=message.message_id,
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
            await message.reply_text(
                FORMAT_HELP,
                parse_mode="Markdown",
                reply_to_message_id=message.message_id,
            )
            return ConversationHandler.END
        llm_result, raw_response = await parse_with_llm(raw_text, participant_names)
        if isinstance(llm_result, str):
            await _notify_admin_llm_error(
                context,
                message.from_user,
                raw_text,
                llm_result,
                raw_response,
            )
            await message.reply_text(
                llm_result,
                parse_mode="Markdown",
                reply_to_message_id=message.message_id,
            )
            return ConversationHandler.END
        if llm_result:
            expense = llm_result
            logger.info(f"LLM parsed: {expense}")

    if not expense:
        await message.reply_text(
            FORMAT_HELP,
            parse_mode="Markdown",
            reply_to_message_id=message.message_id,
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

    if not context.user_data.get("expense_title"):
        await message.reply_text(
            "Enter expense title:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. Dinner"),
            reply_to_message_id=message.message_id,
        )
        return TITLE

    if not context.user_data.get("expense_amount"):
        await message.reply_text(
            f"*{context.user_data['expense_title']}*\nEnter amount:",
            parse_mode="Markdown",
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
            reply_to_message_id=message.message_id,
        )
        return AMOUNT

    if not context.user_data.get("payer_id"):
        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        await message.reply_text(
            f"*{title}* — {amount:.2f}\n\nWho paid?",
            parse_mode="Markdown",
            reply_markup=participant_keyboard(participants_map, CB_PAYER),
            reply_to_message_id=message.message_id,
        )
        return PAYER

    if not context.user_data.get("selected_payees"):
        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        payer_name = context.user_data["payer_name"]
        await message.reply_text(
            f"*{title}* — {amount:.2f}\nPaid by: {payer_name}\n\nSelect who to split with:",
            parse_mode="Markdown",
            reply_markup=participant_keyboard(
                participants_map, CB_PAYEE, done_btn=("< Done >", CB_PAYEE_DONE)
            ),
            reply_to_message_id=message.message_id,
        )
        return PAYEES

    confirmation_text, markup = _store_pending_expense(
        context.user_data,
        user_id,
        message.message_id,
        tg_name,
        context.user_data["selected_payees"],
        group_id,
    )
    _reset_add_state(context.user_data)
    await message.reply_text(confirmation_text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not is_allowed_chat(update) or not update.message or not update.effective_user:
        return ConversationHandler.END
    assert context.user_data is not None
    _reset_add_state(context.user_data)
    resolved = resolve_group(update, context.user_data)
    if not resolved:
        if is_dm(update):
            if not ALL_GROUP_IDS:
                await update.message.reply_text(
                    "No groups configured.",
                    reply_to_message_id=update.message.message_id,
                )
                return ConversationHandler.END
            context.user_data["pending_cmd"] = "add"
            context.user_data["pending_cmd_text"] = (update.message.text or "").strip()
            await update.message.reply_text(
                "Select a group first:",
                reply_markup=group_picker_keyboard(group_picker_options()),
                reply_to_message_id=update.message.message_id,
            )
            return SELECT_GROUP
        await update.message.reply_text(NO_GROUP_MSG, reply_to_message_id=update.message.message_id)
        return ConversationHandler.END
    group_id, client = resolved

    return await _continue_add_flow(
        update.message,
        context,
        update.effective_user.id,
        tg_display_name(update),
        group_id,
        client,
        (update.message.text or "").strip(),
    )


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

    resolved = resolve_group(update, context.user_data)
    assert resolved
    _group_id, client = resolved
    try:
        participants_map = client.get_participants()
        context.user_data["participants_map"] = participants_map
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Who paid?",
        reply_markup=participant_keyboard(participants_map, CB_PAYER),
        reply_to_message_id=update.message.message_id,
    )
    return PAYER


async def interactive_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and context.user_data is not None
    await query.answer()

    payer_id = query.data[len(CB_PAYER) :]
    participants_map = context.user_data["participants_map"]
    reverse = {pid: name for name, pid in participants_map.items()}

    context.user_data["payer_id"] = payer_id
    context.user_data["payer_name"] = reverse[payer_id]

    pre_selected = context.user_data.get("selected_payees", [])
    if pre_selected:
        assert query.message and update.effective_user
        resolved = resolve_group(update, context.user_data)
        assert resolved
        group_id, _client = resolved
        text, markup = _store_pending_expense(
            context.user_data,
            update.effective_user.id,
            query.message.message_id,
            tg_display_name(update),
            pre_selected,
            group_id,
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    context.user_data["selected_payees"] = []
    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=participant_keyboard(
            participants_map, CB_PAYEE, done_btn=("< Done >", CB_PAYEE_DONE)
        ),
    )
    return PAYEES


async def interactive_payees(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and update.effective_user and context.user_data is not None
    await query.answer()

    data: str = query.data
    if data == CB_PAYEE_DONE:
        selected: list[str] = context.user_data.get("selected_payees", [])
        if not selected:
            await query.answer("Select at least one person", show_alert=True)
            return PAYEES

        assert query.message
        resolved = resolve_group(update, context.user_data)
        assert resolved
        group_id, _client = resolved
        text, markup = _store_pending_expense(
            context.user_data,
            update.effective_user.id,
            query.message.message_id,
            tg_display_name(update),
            selected,
            group_id,
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return ConversationHandler.END

    payee_id = data[len(CB_PAYEE) :]
    participants_map = context.user_data["participants_map"]
    selected = context.user_data.get("selected_payees", [])
    if payee_id == CB_PAYEE_ALL:
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
            participants_map, CB_PAYEE, set(selected), done_btn=("✓ Done", CB_PAYEE_DONE)
        ),
    )
    return PAYEES


async def cancel_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and context.user_data is not None
    _reset_add_state(context.user_data)
    await update.message.reply_text(
        "Cancelled.",
        reply_to_message_id=update.message.message_id,
    )
    return ConversationHandler.END


async def interactive_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and context.user_data is not None
    await query.answer()

    if not query.data.startswith(CB_SELECT_GROUP):
        return SELECT_GROUP

    group_id = query.data[len(CB_SELECT_GROUP) :]
    context.user_data["active_group"] = group_id
    client = get_spliit(group_id)
    label = _group_name(client, group_id)

    pending_cmd = context.user_data.pop("pending_cmd", None)
    pending_text = context.user_data.pop("pending_cmd_text", None)

    if pending_cmd == "add":
        _reset_add_state(context.user_data)
        await query.edit_message_text(f"Group: {label}")
        assert update.effective_user and query.message
        message = cast(Message, query.message)
        return await _continue_add_flow(
            message,
            context,
            update.effective_user.id,
            tg_display_name(update),
            group_id,
            client,
            pending_text or "/add",
        )

    await query.edit_message_text(f"Switched to: {label}")
    return ConversationHandler.END
