"""Telegram prompts for progressing an expense draft."""

from __future__ import annotations

from typing import cast

from telegram import CallbackQuery, ForceReply, Message

from constants import (
    AMOUNT,
    CB_PAYEE,
    CB_PAYEE_DONE,
    CB_PAYER,
    PAYEES,
    PAYER,
    SPLIT_MODE,
    SPLIT_VALUES,
    TITLE,
    SplitMode,
)
from expense_draft import ExpenseDraft
from expense_intake import IntakeField
from keyboards import participant_keyboard, split_mode_keyboard

_SPLIT_MODE_PROMPT = "How do you want to split it?"


async def render_needs_input_message(
    message: Message, draft: ExpenseDraft, field: IntakeField
) -> int:
    match field:
        case IntakeField.TITLE:
            return await prompt_title(message)
        case IntakeField.AMOUNT:
            return await prompt_amount(message, draft)
        case IntakeField.PAYER:
            return await prompt_payer(message, draft)
        case IntakeField.PAYEES:
            return await prompt_payees(message, draft)
        case IntakeField.SPLIT_MODE:
            return await prompt_split_mode_new_message(message)
        case IntakeField.SPLIT_VALUES:
            await prompt_split_values_message(message, draft)
            return SPLIT_VALUES


async def prompt_title(message: Message) -> int:
    await message.reply_text(
        "Enter expense title:",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. Dinner"),
        reply_to_message_id=message.message_id,
    )
    return TITLE


async def prompt_amount(message: Message, draft: ExpenseDraft) -> int:
    await message.reply_text(
        f"*{draft.title}*\nEnter amount:",
        parse_mode="Markdown",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
        reply_to_message_id=message.message_id,
    )
    return AMOUNT


async def prompt_invalid_amount(message: Message, user_message: str) -> int:
    await message.reply_text(
        user_message,
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
        reply_to_message_id=message.message_id,
    )
    return AMOUNT


async def prompt_payer(message: Message, draft: ExpenseDraft) -> int:
    assert draft.amount is not None
    await message.reply_text(
        f"*{draft.title}* — {draft.amount:.2f}\n\nWho paid?",
        parse_mode="Markdown",
        reply_markup=participant_keyboard(draft.participants_map, CB_PAYER),
        reply_to_message_id=message.message_id,
    )
    return PAYER


async def prompt_payees(message: Message, draft: ExpenseDraft) -> int:
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


async def prompt_split_mode_new_message(message: Message) -> int:
    await message.reply_text(
        _SPLIT_MODE_PROMPT,
        reply_markup=split_mode_keyboard(),
        reply_to_message_id=message.message_id,
    )
    return SPLIT_MODE


async def prompt_split_mode_edit(query: CallbackQuery) -> int:
    await query.edit_message_text(_SPLIT_MODE_PROMPT, reply_markup=split_mode_keyboard())
    return SPLIT_MODE


def split_values_prompt(draft: ExpenseDraft) -> str:
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


async def prompt_split_values_message(message: Message, draft: ExpenseDraft) -> None:
    await message.reply_text(
        split_values_prompt(draft),
        reply_markup=ForceReply(selective=True),
        reply_to_message_id=message.message_id,
    )


async def prompt_split_values_retry(message: Message, user_message: str) -> int:
    await message.reply_text(
        user_message,
        reply_markup=ForceReply(selective=True),
        reply_to_message_id=message.message_id,
    )
    return SPLIT_VALUES


async def prompt_split_values_edit(query: CallbackQuery, draft: ExpenseDraft) -> int:
    await query.edit_message_text(split_values_prompt(draft))
    assert query.message
    message = cast(Message, query.message)
    await message.reply_text(
        "Reply with the values:",
        reply_markup=ForceReply(selective=True),
        reply_to_message_id=message.message_id,
    )
    return SPLIT_VALUES
