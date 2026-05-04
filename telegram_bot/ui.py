from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import cast

from telegram import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes, ConversationHandler

from config import USERS_JSON_PATH
from domain import ParticipantDirectory, format_money
from domain.balance import Balance, Reimbursement
from domain.expense import ExpenseDraft, IntakeField
from domain.registry import load_user_directory
from domain.split import SplitMode
from spliit_integration.gateway import gateway
from telegram_bot.constants import (
    AMOUNT,
    CB_CANCEL,
    CB_CONFIRM,
    CB_PAYEE,
    CB_PAYEE_DONE,
    CB_PAYER,
    PAYEES,
    PAYER,
    SPLIT_MODE,
    SPLIT_VALUES,
    TITLE,
)
from telegram_bot.keyboards import participant_keyboard, split_mode_keyboard
from telegram_bot.session import PendingExpense, Session

logger = logging.getLogger(__name__)

_SPLIT_MODE_PROMPT = "How do you want to split it?"

type TelegramMarkup = ForceReply | InlineKeyboardMarkup | None


@dataclass(frozen=True, slots=True)
class MessageAction:
    text: str
    markup: TelegramMarkup = None
    parse_mode: str | None = None
    edit: bool = False
    alert: bool = False


@dataclass(frozen=True, slots=True)
class ConversationReply:
    next_state: int
    actions: tuple[MessageAction, ...] = ()

    async def deliver(self, query: CallbackQuery | None, message: Message) -> int:
        if query is not None and not any(action.alert for action in self.actions):
            await query.answer()
        for action in self.actions:
            if action.alert:
                assert query is not None
                await query.answer(action.text, show_alert=True)
                continue
            if action.edit:
                assert query is not None
                await query.edit_message_text(
                    action.text,
                    parse_mode=action.parse_mode,
                    reply_markup=cast(InlineKeyboardMarkup | None, action.markup),
                )
                continue
            await message.reply_text(
                action.text,
                parse_mode=action.parse_mode,
                reply_markup=action.markup,
                reply_to_message_id=message.message_id,
            )
        return self.next_state


def error_reply(error: Exception) -> ConversationReply:
    return ConversationReply(
        ConversationHandler.END,
        (MessageAction(f"Error: {error}"),),
    )


def expense_confirmation_reply(
    *,
    draft: ExpenseDraft,
    key: str,
    tg_name: str,
    group_id: str,
    split_mode: SplitMode,
    paid_for: list[tuple[str, int]] | None,
    bot_data: dict | None,
    edit: bool,
) -> ConversationReply:
    directory = gateway.group(group_id).directory
    text, markup = store_expense_confirmation(
        draft=draft,
        key=key,
        tg_name=tg_name,
        group_id=group_id,
        split_mode=split_mode,
        paid_for=paid_for,
        currency=directory.currency,
        bot_data=bot_data,
    )
    return ConversationReply(
        ConversationHandler.END,
        (MessageAction(text, markup, parse_mode="Markdown", edit=edit),),
    )


@dataclass(frozen=True, slots=True)
class ExpenseConfirmation:
    text: str
    markup: InlineKeyboardMarkup
    pending_expense: PendingExpense


def expense_prompt_reply(
    draft: ExpenseDraft,
    field: IntakeField,
    *,
    edit: bool,
) -> ConversationReply:
    match field:
        case IntakeField.TITLE:
            return ConversationReply(
                TITLE,
                (
                    MessageAction(
                        "Enter expense title:",
                        ForceReply(selective=True, input_field_placeholder="e.g. Dinner"),
                    ),
                ),
            )
        case IntakeField.AMOUNT:
            return ConversationReply(
                AMOUNT,
                (
                    MessageAction(
                        f"*{draft.title}*\nEnter amount:",
                        ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
                        parse_mode="Markdown",
                    ),
                ),
            )
        case IntakeField.PAYER:
            assert draft.amount is not None
            return ConversationReply(
                PAYER,
                (
                    MessageAction(
                        f"*{draft.title}* — {draft.amount:.2f}\n\nWho paid?",
                        participant_keyboard(draft.participants_map, CB_PAYER),
                        parse_mode="Markdown",
                        edit=edit,
                    ),
                ),
            )
        case IntakeField.PAYEES:
            assert draft.amount is not None
            return ConversationReply(
                PAYEES,
                (
                    MessageAction(
                        f"*{draft.title}* — {draft.amount:.2f}\n"
                        f"Paid by: {draft.payer_name}\n\nSelect who to split with:",
                        participant_keyboard(
                            draft.participants_map,
                            CB_PAYEE,
                            set(draft.payee_ids),
                            done_btn=(
                                "✓ Done" if draft.payee_ids else "< Done >",
                                CB_PAYEE_DONE,
                            ),
                        ),
                        parse_mode="Markdown",
                        edit=edit,
                    ),
                ),
            )
        case IntakeField.SPLIT_MODE:
            return ConversationReply(
                SPLIT_MODE,
                (
                    MessageAction(
                        _SPLIT_MODE_PROMPT,
                        split_mode_keyboard(),
                        edit=edit,
                    ),
                ),
            )
        case IntakeField.SPLIT_VALUES:
            prompt = split_values_prompt(draft)
            if edit:
                return ConversationReply(
                    SPLIT_VALUES,
                    (
                        MessageAction(prompt, edit=True),
                        MessageAction("Reply with the values:", ForceReply(selective=True)),
                    ),
                )
            return ConversationReply(
                SPLIT_VALUES,
                (MessageAction(prompt, ForceReply(selective=True)),),
            )


def invalid_amount_reply(user_message: str) -> ConversationReply:
    return ConversationReply(
        AMOUNT,
        (
            MessageAction(
                user_message,
                ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
            ),
        ),
    )


def split_values_retry_reply(user_message: str) -> ConversationReply:
    return ConversationReply(
        SPLIT_VALUES,
        (MessageAction(user_message, ForceReply(selective=True)),),
    )


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


def format_confirmation(
    title: str,
    amount: float,
    payer: str,
    payees: list[str],
    split_mode: SplitMode = SplitMode.EVENLY,
    paid_for_named: list[tuple[str, int]] | None = None,
    currency: str = "",
) -> str:
    header = f"**{title}**\nAmount: {amount:.2f}\nPaid by: {payer}\n"
    if split_mode is SplitMode.EVENLY:
        share = amount / len(payees)
        body = f"Split: {', '.join(payees)}\nEach: {share:.2f}\n"
    else:
        assert paid_for_named is not None
        body = f"Split mode: {_split_mode_label(split_mode)}\n"
        body += "\n".join(
            f"  • {name}: {_format_share(split_mode, share, currency)}"
            for name, share in paid_for_named
        )
        body += "\n"
    return header + body + "\nConfirm?"


def confirm_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm", callback_data=f"{CB_CONFIRM}{key}"),
                InlineKeyboardButton("Cancel", callback_data=f"{CB_CANCEL}{key}"),
            ]
        ]
    )


def _split_mode_label(mode: SplitMode) -> str:
    return {
        SplitMode.EVENLY: "Equally",
        SplitMode.BY_SHARES: "By shares",
        SplitMode.BY_PERCENTAGE: "By percentage",
        SplitMode.BY_AMOUNT: "By amount",
    }[mode]


def _format_share(mode: SplitMode, share: int, currency: str) -> str:
    if mode is SplitMode.BY_SHARES:
        return f"{share} share{'s' if share != 1 else ''}"
    if mode is SplitMode.BY_PERCENTAGE:
        return f"{share / 100:.2f}%"
    if mode is SplitMode.BY_AMOUNT:
        return format_money(share, currency)
    return str(share)


def build_expense_confirmation(
    draft: ExpenseDraft,
    key: str,
    tg_name: str,
    group_id: str,
    split_mode: SplitMode = SplitMode.EVENLY,
    paid_for: list[tuple[str, int]] | None = None,
    currency: str = "",
) -> ExpenseConfirmation:
    assert draft.title is not None
    assert draft.amount is not None
    assert draft.payer_name is not None

    if paid_for is None:
        paid_for = [(pid, 1) for pid in draft.payee_ids]

    pending_expense = PendingExpense(
        expense=draft.confirm(split_mode=split_mode, paid_for=paid_for),
        tg_name=tg_name,
        group_id=group_id,
    )
    reverse = draft.id_to_name()
    paid_for_named = [(reverse[pid], share) for pid, share in paid_for]
    return ExpenseConfirmation(
        text=format_confirmation(
            draft.title,
            draft.amount,
            draft.payer_name,
            draft.payee_names(),
            split_mode=split_mode,
            paid_for_named=paid_for_named,
            currency=currency,
        ),
        markup=confirm_keyboard(key),
        pending_expense=pending_expense,
    )


def store_expense_confirmation(
    draft: ExpenseDraft,
    key: str,
    tg_name: str,
    group_id: str,
    split_mode: SplitMode = SplitMode.EVENLY,
    paid_for: list[tuple[str, int]] | None = None,
    currency: str = "",
    bot_data: dict | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    confirmation = build_expense_confirmation(
        draft=draft,
        key=key,
        tg_name=tg_name,
        group_id=group_id,
        split_mode=split_mode,
        paid_for=paid_for,
        currency=currency,
    )
    Session(None, bot_data).stash(key, confirmation.pending_expense)
    return confirmation.text, confirmation.markup


def format_balance_lines(
    group_name: str,
    balances: list[Balance],
    reimbursements: list[Reimbursement],
    directory: ParticipantDirectory,
) -> list[str]:
    lines = [f"**{group_name}** Balances\n"]
    for balance in balances:
        total = balance.total_cents
        sign = "+" if total > 0 else ""
        lines.append(
            f"- {directory.participant_name(balance.participant_id)}: "
            f"{sign}{format_money(total, directory.currency)}"
        )

    if reimbursements:
        lines.append("\n**Suggested Payments:**")
        for reimbursement in reimbursements:
            lines.append(format_reimbursement_text(reimbursement, directory, prefix="- "))
    return lines


def format_reimbursement_text(
    reimbursement: Reimbursement,
    directory: ParticipantDirectory,
    prefix: str = "",
) -> str:
    from_name = directory.participant_name(reimbursement.from_id)
    to_name = directory.participant_name(reimbursement.to_id)
    amount = format_money(reimbursement.amount_cents, directory.currency)
    return f"{prefix}{from_name} -> {to_name}: {amount}"


def format_settlement_option_label(
    reimbursement: Reimbursement, directory: ParticipantDirectory
) -> str:
    from_name = directory.participant_name(reimbursement.from_id)
    to_name = directory.participant_name(reimbursement.to_id)
    amount = format_money(reimbursement.amount_cents, directory.currency)
    return f"{from_name} -> {to_name} ({amount})"


def format_settlement_line(
    index: int, reimbursement: Reimbursement, directory: ParticipantDirectory
) -> str:
    from_name = html.escape(directory.participant_name(reimbursement.from_id))
    to_name = html.escape(directory.participant_name(reimbursement.to_id))
    amount = html.escape(format_money(reimbursement.amount_cents, directory.currency))
    return f"{index}. <b>{from_name}</b> owes <b>{to_name}</b> {amount}"


def format_split_line(
    split_mode: SplitMode,
    paid_for: list[tuple[str, int]],
    directory: ParticipantDirectory,
    amount_cents: int,
) -> str:
    payee_names = [directory.id_to_name.get(pid, "Unknown") for pid, _ in paid_for]
    if split_mode is SplitMode.EVENLY:
        share = amount_cents / 100 / len(payee_names)
        return (
            f"Split ({html.escape(directory.currency)}{share:.2f} each): "
            f"{html.escape(', '.join(payee_names))}"
        )

    parts: list[str] = []
    for (_, share), name in zip(paid_for, payee_names, strict=True):
        if split_mode is SplitMode.BY_SHARES:
            parts.append(f"{html.escape(name)} ({share})")
        elif split_mode is SplitMode.BY_PERCENTAGE:
            parts.append(f"{html.escape(name)} ({share / 100:g}%)")
        else:
            parts.append(f"{html.escape(name)} ({format_money(share, directory.currency)})")
    label = {
        SplitMode.BY_SHARES: "shares",
        SplitMode.BY_PERCENTAGE: "%",
        SplitMode.BY_AMOUNT: "amount",
    }[split_mode]
    return f"Split by {label}: {', '.join(parts)}"


def format_expense_receipt(
    title: str,
    amount_cents: int,
    payer_id: str,
    paid_for: list[tuple[str, int]],
    split_mode: SplitMode,
    directory: ParticipantDirectory,
    mentions: list[str],
) -> str:
    payer_name = directory.id_to_name.get(payer_id, "Unknown")
    split_line = format_split_line(split_mode, paid_for, directory, amount_cents)
    return (
        f"💸 <b>{html.escape(title)}</b> added\n"
        f"Amount: {format_money(amount_cents, directory.currency)}\n"
        f"Paid by: {html.escape(payer_name)}\n"
        f"{split_line}\n\n"
        f"👋 {' '.join(mentions)}"
    )


def involved_names(
    payer_id: str,
    paid_for: list[tuple[str, int]],
    directory: ParticipantDirectory,
) -> set[str]:
    payer_name = directory.id_to_name.get(payer_id, "Unknown")
    payee_names = [directory.id_to_name.get(pid, "Unknown") for pid, _ in paid_for]
    return {*payee_names, payer_name}


async def build_mention(name: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    tg_id = load_user_directory(USERS_JSON_PATH).telegram_id(name)
    if not tg_id:
        return name
    try:
        chat = await context.bot.get_chat(int(tg_id))
        if chat.username:
            return f"@{chat.username}"
        display = chat.first_name or name
        return f'<a href="tg://user?id={tg_id}">{display}</a>'
    except Exception:
        return f'<a href="tg://user?id={tg_id}">{name}</a>'


async def reply_to_callback(query: CallbackQuery, text: str) -> None:
    if query.message:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            logger.error("Failed to clear callback markup: %s", e)
        message = cast(Message, query.message)
        await message.reply_text(text, reply_to_message_id=message.message_id)
    else:
        await query.edit_message_text(text)
