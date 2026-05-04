"""User-facing receipt text after an expense is created."""

from __future__ import annotations

import html

from constants import SplitMode, format_money
from domain import ParticipantDirectory


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
        else:  # BY_AMOUNT
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
