"""Expense confirmation creation for the /add flow."""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from constants import CB_CANCEL, CB_CONFIRM, PendingExpense, SplitMode, format_money
from expense_draft import ExpenseDraft
from pending_store import pending


@dataclass(frozen=True, slots=True)
class ExpenseConfirmation:
    text: str
    markup: InlineKeyboardMarkup
    pending_expense: PendingExpense


def format_confirmation(
    title: str,
    amount: float,
    payer: str,
    payees: list[str],
    split_mode: SplitMode = SplitMode.EVENLY,
    paid_for_named: list[tuple[str, int]] | None = None,
    currency: str = "",
) -> str:
    """Render a pending-expense confirmation message."""
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
    """Build the pending expense and user-facing confirmation from a draft."""
    assert draft.title is not None
    assert draft.amount is not None
    assert draft.payer_name is not None

    if paid_for is None:
        paid_for = [(pid, 1) for pid in draft.payee_ids]

    pending_expense = draft.to_pending_expense(
        tg_name=tg_name,
        group_id=group_id,
        split_mode=split_mode,
        paid_for=paid_for,
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
) -> tuple[str, InlineKeyboardMarkup]:
    """Store a pending expense and return the confirmation message payload."""
    confirmation = build_expense_confirmation(
        draft=draft,
        key=key,
        tg_name=tg_name,
        group_id=group_id,
        split_mode=split_mode,
        paid_for=paid_for,
        currency=currency,
    )
    pending[key] = confirmation.pending_expense
    return confirmation.text, confirmation.markup
