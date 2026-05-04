"""The /add conversation flow (multi-step expense creation)."""

from __future__ import annotations

import logging
from typing import cast

from spliit import Spliit
from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import (
    ALL_GROUP_IDS,
    get_spliit,
)
from constants import (
    CB_PAYEE,
    CB_PAYEE_DONE,
    CB_PAYER,
    CB_SELECT_GROUP,
    CB_SPLIT_MODE,
    PAYEES,
    SELECT_GROUP,
    SPLIT_MODE,
    SplitMode,
)
from domain import participant_directory
from expense_confirmation import store_expense_confirmation
from expense_draft import ExpenseDraft
from expense_draft_store import clear_draft, get_draft, set_draft
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
from expense_prompts import (
    prompt_invalid_amount,
    prompt_split_mode_edit,
    prompt_split_values_edit,
    prompt_split_values_retry,
    render_needs_input_message,
)
from group_resolution import DM_NO_GROUP_MSG, NO_GROUP_MSG, resolve_group
from group_selection import group_name, group_picker_options
from helpers import (
    is_allowed_chat,
    is_dm,
    tg_display_name,
)
from keyboards import group_picker_keyboard, participant_keyboard
from llm_error_reporting import notify_admin_llm_error
from parsing import transcribe_voice
from user_session import pop_pending_add, remember_pending_add, set_active_group

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
    assert context.user_data is not None

    if empty_draft_started(text):
        draft = ExpenseDraft()
        set_draft(context.user_data, draft)
        return await render_needs_input_message(message, draft, IntakeField.TITLE)

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
        return await render_needs_input_message(message, draft, outcome.field)
    if isinstance(outcome, Rejected):
        if outcome.admin_report:
            await notify_admin_llm_error(
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
    clear_draft(context.user_data)
    resolved = resolve_group(update, context.user_data)
    if not resolved:
        if is_dm(update):
            if not ALL_GROUP_IDS:
                await update.message.reply_text(
                    "No groups configured.",
                    reply_to_message_id=update.message.message_id,
                )
                return ConversationHandler.END
            remember_pending_add(context.user_data, (update.message.text or "").strip())
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
    return await render_needs_input_message(update.message, draft, outcome.field)


async def interactive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text and context.user_data is not None
    draft = get_draft(context.user_data)
    outcome = apply_amount(draft, update.message.text)
    if isinstance(outcome, Rejected):
        return await prompt_invalid_amount(update.message, outcome.user_message)

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
    return await render_needs_input_message(update.message, draft, outcome.field)


async def interactive_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and context.user_data is not None
    await query.answer()

    payer_id = query.data[len(CB_PAYER) :]
    draft = get_draft(context.user_data)
    participants_map = draft.participants_map

    outcome = apply_payer(draft, payer_id)

    if isinstance(outcome, NeedsInput) and outcome.field is IntakeField.SPLIT_MODE:
        return await prompt_split_mode_edit(query)

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

        return await prompt_split_mode_edit(query)

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
        return await prompt_split_values_edit(query, draft)
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
        return await prompt_split_values_retry(update.message, outcome.user_message)

    assert isinstance(outcome, ReadyToConfirm)
    return await _finalize_pending_via_update_message(
        update, context, outcome.split_mode, outcome.paid_for
    )


def _store_current_draft_confirmation(
    user_data: dict,
    key: str,
    tg_name: str,
    group_id: str,
    client: Spliit,
    split_mode: SplitMode,
    paid_for: list[tuple[str, int]] | None,
):
    directory = participant_directory(client)
    return store_expense_confirmation(
        draft=get_draft(user_data),
        key=key,
        tg_name=tg_name,
        group_id=group_id,
        split_mode=split_mode,
        paid_for=paid_for,
        currency=directory.currency,
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
    text, markup = _store_current_draft_confirmation(
        context.user_data,
        key=f"{update.effective_user.id}_{query.message.message_id}",
        tg_name=tg_display_name(update),
        group_id=group_id,
        client=client,
        split_mode=split_mode,
        paid_for=paid_for,
    )
    clear_draft(context.user_data)
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
    text, markup = _store_current_draft_confirmation(
        context.user_data,
        key=f"{user_id}_{message.message_id}",
        tg_name=tg_name,
        group_id=group_id,
        client=client,
        split_mode=split_mode,
        paid_for=paid_for,
    )
    clear_draft(context.user_data)
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
    clear_draft(context.user_data)
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
    clear_draft(context.user_data)

    resolved = resolve_group(update, context.user_data)
    if not resolved:
        await update.message.reply_text(
            DM_NO_GROUP_MSG if is_dm(update) else NO_GROUP_MSG,
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
    set_active_group(context.user_data, group_id)
    client = get_spliit(group_id)
    label = group_name(client, group_id)

    pending_add_text = pop_pending_add(context.user_data)

    if pending_add_text is not None:
        clear_draft(context.user_data)
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
            pending_add_text,
        )

    await query.edit_message_text(f"Switched to: {label}")
    return ConversationHandler.END
