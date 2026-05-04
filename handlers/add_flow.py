"""The /add conversation flow (multi-step expense creation)."""

from __future__ import annotations

import logging
from typing import cast

from spliit import Spliit
from telegram import CallbackQuery, ForceReply, Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import (
    ALL_GROUP_IDS,
    get_spliit,
)
from constants import (
    AMOUNT,
    CB_PAYEE,
    CB_PAYEE_DONE,
    CB_PAYER,
    CB_SELECT_GROUP,
    CB_SPLIT_MODE,
    PAYEES,
    PAYER,
    SELECT_GROUP,
    SPLIT_MODE,
    SPLIT_VALUES,
    TITLE,
    SplitMode,
)
from domain import group_picker_options, id_to_name_map
from expense_draft import ExpenseDraft, get_draft, set_draft
from expense_intake import (
    Ended,
    IntakeField,
    NeedsInput,
    ReadyToConfirm,
    Rejected,
    apply_amount,
    apply_payer,
    apply_split_mode,
    apply_split_values,
    apply_title,
    complete_payees,
    empty_draft_started,
    start_from_text,
    toggle_payee,
)
from helpers import (
    group_picker_keyboard,
    is_allowed_chat,
    is_dm,
    participant_keyboard,
    split_mode_keyboard,
    tg_display_name,
)
from parsing import transcribe_voice

from .common import (
    NO_GROUP_MSG,
    _group_name,
    _notify_admin_llm_error,
    _reset_add_state,
    _store_pending_expense,
    resolve_group,
)

logger = logging.getLogger(__name__)


_SPLIT_MODE_PROMPT = "How do you want to split it?"


async def _prompt_title(message: Message) -> int:
    await message.reply_text(
        "Enter expense title:",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. Dinner"),
        reply_to_message_id=message.message_id,
    )
    return TITLE


async def _prompt_amount(message: Message, draft: ExpenseDraft) -> int:
    await message.reply_text(
        f"*{draft.title}*\nEnter amount:",
        parse_mode="Markdown",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
        reply_to_message_id=message.message_id,
    )
    return AMOUNT


async def _prompt_payer(message: Message, draft: ExpenseDraft) -> int:
    assert draft.amount is not None
    await message.reply_text(
        f"*{draft.title}* — {draft.amount:.2f}\n\nWho paid?",
        parse_mode="Markdown",
        reply_markup=participant_keyboard(draft.participants_map, CB_PAYER),
        reply_to_message_id=message.message_id,
    )
    return PAYER


async def _prompt_payees(message: Message, draft: ExpenseDraft) -> int:
    assert draft.amount is not None
    await message.reply_text(
        f"*{draft.title}* — {draft.amount:.2f}\n"
        f"Paid by: {draft.payer_name}\n\nSelect who to split with:",
        parse_mode="Markdown",
        reply_markup=participant_keyboard(
            draft.participants_map, CB_PAYEE, done_btn=("< Done >", CB_PAYEE_DONE)
        ),
        reply_to_message_id=message.message_id,
    )
    return PAYEES


async def _render_needs_input_message(
    message: Message, draft: ExpenseDraft, field: IntakeField
) -> int:
    match field:
        case IntakeField.TITLE:
            return await _prompt_title(message)
        case IntakeField.AMOUNT:
            return await _prompt_amount(message, draft)
        case IntakeField.PAYER:
            return await _prompt_payer(message, draft)
        case IntakeField.PAYEES:
            return await _prompt_payees(message, draft)
        case IntakeField.SPLIT_MODE:
            return await _prompt_split_mode_new_message(message)
        case IntakeField.SPLIT_VALUES:
            await _prompt_split_values_message(message, draft)
            return SPLIT_VALUES


async def _prompt_split_mode_new_message(message: Message) -> int:
    await message.reply_text(
        _SPLIT_MODE_PROMPT,
        reply_markup=split_mode_keyboard(),
        reply_to_message_id=message.message_id,
    )
    return SPLIT_MODE


async def _prompt_split_mode_edit(query: CallbackQuery) -> int:
    await query.edit_message_text(_SPLIT_MODE_PROMPT, reply_markup=split_mode_keyboard())
    return SPLIT_MODE


def _split_values_prompt(draft: ExpenseDraft) -> str:
    assert draft.split_mode is not None
    assert draft.amount is not None
    example = {
        SplitMode.BY_SHARES: "e.g. 2 1 1",
        SplitMode.BY_PERCENTAGE: "e.g. 50 30 20",
        SplitMode.BY_AMOUNT: f"e.g. amounts that sum to {draft.amount:.2f}",
    }[draft.split_mode]
    label = {
        SplitMode.BY_SHARES: "shares",
        SplitMode.BY_PERCENTAGE: "percentages (must sum to 100)",
        SplitMode.BY_AMOUNT: f"amounts (must sum to {draft.amount:.2f})",
    }[draft.split_mode]
    return f"Enter {label} for each payee in order:\n{', '.join(draft.payee_names())}\n{example}"


async def _prompt_split_values_message(message: Message, draft: ExpenseDraft) -> None:
    await message.reply_text(
        _split_values_prompt(draft),
        reply_markup=ForceReply(selective=True),
        reply_to_message_id=message.message_id,
    )


async def _prompt_split_values_edit(query: CallbackQuery, draft: ExpenseDraft) -> int:
    await query.edit_message_text(_split_values_prompt(draft))
    assert query.message
    message = cast(Message, query.message)
    await message.reply_text(
        "Reply with the values:",
        reply_markup=ForceReply(selective=True),
        reply_to_message_id=message.message_id,
    )
    return SPLIT_VALUES


async def _continue_add_flow(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    tg_name: str,
    group_id: str,
    client: Spliit,
    text: str,
) -> int:
    assert context.user_data is not None

    if empty_draft_started(text):
        draft = ExpenseDraft()
        set_draft(context.user_data, draft)
        return await _prompt_title(message)

    try:
        participants_map = client.get_participants()
    except Exception as e:
        await message.reply_text(
            f"Error: {e}",
            reply_to_message_id=message.message_id,
        )
        return ConversationHandler.END

    draft, outcome = await start_from_text(text, participants_map)
    set_draft(context.user_data, draft)
    if isinstance(outcome, NeedsInput):
        return await _render_needs_input_message(message, draft, outcome.field)
    if isinstance(outcome, Rejected):
        if outcome.admin_report:
            await _notify_admin_llm_error(
                context,
                message.from_user,
                outcome.admin_report.raw_text,
                outcome.admin_report.user_message,
                outcome.admin_report.raw_response,
            )
        await message.reply_text(
            outcome.user_message,
            parse_mode="Markdown",
            reply_to_message_id=message.message_id,
        )
        return ConversationHandler.END
    if isinstance(outcome, Ended):
        if outcome.user_message:
            await message.reply_text(
                outcome.user_message,
                parse_mode="Markdown",
                reply_to_message_id=message.message_id,
            )
        return ConversationHandler.END
    if isinstance(outcome, ReadyToConfirm):
        return await _finalize_pending_via_message(
            message, context, user_id, tg_name, group_id, outcome.split_mode, outcome.paid_for
        )


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
    draft = get_draft(context.user_data)
    outcome = apply_title(draft, update.message.text)
    assert isinstance(outcome, NeedsInput)
    return await _render_needs_input_message(update.message, draft, outcome.field)


async def interactive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text and context.user_data is not None
    draft = get_draft(context.user_data)
    outcome = apply_amount(draft, update.message.text)
    if isinstance(outcome, Rejected):
        await update.message.reply_text(
            outcome.user_message,
            reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
            reply_to_message_id=update.message.message_id,
        )
        return AMOUNT

    resolved = resolve_group(update, context.user_data)
    assert resolved
    _group_id, client = resolved
    try:
        draft.participants_map = client.get_participants()
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    assert isinstance(outcome, NeedsInput)
    return await _render_needs_input_message(update.message, draft, outcome.field)


async def interactive_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and context.user_data is not None
    await query.answer()

    payer_id = query.data[len(CB_PAYER) :]
    draft = get_draft(context.user_data)
    participants_map = draft.participants_map

    outcome = apply_payer(draft, payer_id)

    if isinstance(outcome, NeedsInput) and outcome.field is IntakeField.SPLIT_MODE:
        return await _prompt_split_mode_edit(query)

    draft.payee_ids = []
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
        draft = get_draft(context.user_data)
        outcome = complete_payees(draft)
        if isinstance(outcome, Rejected):
            await query.answer(outcome.user_message, show_alert=True)
            return PAYEES

        return await _prompt_split_mode_edit(query)

    payee_id = data[len(CB_PAYEE) :]
    draft = get_draft(context.user_data)
    participants_map = draft.participants_map
    toggle_payee(draft, payee_id)
    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=participant_keyboard(
            participants_map, CB_PAYEE, set(draft.payee_ids), done_btn=("✓ Done", CB_PAYEE_DONE)
        ),
    )
    return PAYEES


async def interactive_split_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and update.effective_user and context.user_data is not None
    await query.answer()

    raw = query.data[len(CB_SPLIT_MODE) :]
    draft = get_draft(context.user_data)
    outcome = apply_split_mode(draft, raw)

    if isinstance(outcome, ReadyToConfirm):
        return await _finalize_pending_via_callback(
            update, context, outcome.split_mode, outcome.paid_for
        )
    if isinstance(outcome, NeedsInput) and outcome.field is IntakeField.SPLIT_VALUES:
        return await _prompt_split_values_edit(query, draft)
    return SPLIT_MODE


async def interactive_split_values(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert (
        update.message
        and update.message.text
        and update.effective_user
        and context.user_data is not None
    )

    draft = get_draft(context.user_data)
    outcome = apply_split_values(draft, update.message.text)
    if isinstance(outcome, Ended):
        return ConversationHandler.END
    if isinstance(outcome, Rejected):
        await update.message.reply_text(
            outcome.user_message,
            reply_markup=ForceReply(selective=True),
            reply_to_message_id=update.message.message_id,
        )
        return SPLIT_VALUES

    assert isinstance(outcome, ReadyToConfirm)
    return await _finalize_pending_via_update_message(
        update, context, outcome.split_mode, outcome.paid_for
    )


async def _finalize_pending_via_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    split_mode: SplitMode,
    paid_for: list[tuple[str, int]] | None,
) -> int:
    query = update.callback_query
    assert query and query.message and update.effective_user and context.user_data is not None
    resolved = resolve_group(update, context.user_data)
    assert resolved
    group_id, client = resolved
    _id_name, currency = id_to_name_map(client)
    text, markup = _store_pending_expense(
        context.user_data,
        update.effective_user.id,
        query.message.message_id,
        tg_display_name(update),
        group_id,
        split_mode=split_mode,
        paid_for=paid_for,
        currency=currency,
    )
    _reset_add_state(context.user_data)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END


async def _finalize_pending_via_message(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    tg_name: str,
    group_id: str,
    split_mode: SplitMode,
    paid_for: list[tuple[str, int]] | None,
) -> int:
    assert context.user_data is not None
    client = get_spliit(group_id)
    _id_name, currency = id_to_name_map(client)
    text, markup = _store_pending_expense(
        context.user_data,
        user_id,
        message.message_id,
        tg_name,
        group_id,
        split_mode=split_mode,
        paid_for=paid_for,
        currency=currency,
    )
    _reset_add_state(context.user_data)
    await message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=markup,
        reply_to_message_id=message.message_id,
    )
    return ConversationHandler.END


async def _finalize_pending_via_update_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    split_mode: SplitMode,
    paid_for: list[tuple[str, int]] | None,
) -> int:
    assert update.message and update.effective_user and context.user_data is not None
    resolved = resolve_group(update, context.user_data)
    assert resolved
    group_id, _client = resolved
    return await _finalize_pending_via_message(
        update.message,
        context,
        update.effective_user.id,
        tg_display_name(update),
        group_id,
        split_mode,
        paid_for,
    )


async def cancel_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and context.user_data is not None
    _reset_add_state(context.user_data)
    await update.message.reply_text(
        "Cancelled.",
        reply_to_message_id=update.message.message_id,
    )
    return ConversationHandler.END


async def voice_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.voice or not update.effective_user:
        return
    if not is_allowed_chat(update):
        return

    reply = update.message.reply_to_message
    if not reply or not reply.from_user or not reply.from_user.is_bot:
        return
    if reply.from_user.id != (await context.bot.get_me()).id:
        return

    assert context.user_data is not None
    _reset_add_state(context.user_data)

    resolved = resolve_group(update, context.user_data)
    if not resolved:
        await update.message.reply_text(
            NO_GROUP_MSG if not is_dm(update) else "No group selected. Use /switch to pick one.",
            reply_to_message_id=update.message.message_id,
        )
        return

    group_id, client = resolved
    try:
        participant_names = list(client.get_participants().keys())
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_to_message_id=update.message.message_id,
        )
        return

    voice_file = await update.message.voice.get_file()
    voice_bytes = await voice_file.download_as_bytearray()
    prompt = "Participants: " + ", ".join(participant_names) + "."
    transcript = await transcribe_voice(bytes(voice_bytes), prompt=prompt)
    if not transcript:
        await update.message.reply_text(
            "Couldn't understand the voice message. Please type the expense instead.",
            reply_to_message_id=update.message.message_id,
        )
        return

    logger.info("Voice transcribed: %s", transcript)
    await update.message.reply_text(
        f"Transcribed voice message: {transcript}",
        reply_to_message_id=update.message.message_id,
    )
    await _continue_add_flow(
        update.message,
        context,
        update.effective_user.id,
        tg_display_name(update),
        group_id,
        client,
        transcript,
    )


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
