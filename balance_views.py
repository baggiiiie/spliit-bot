"""Balance and reimbursement presentation helpers."""

from __future__ import annotations

import html

from constants import format_money
from domain import ParticipantDirectory


def format_balance_lines(
    group_name: str,
    balances: dict,
    reimbursements: list[dict],
    directory: ParticipantDirectory,
) -> list[str]:
    lines = [f"**{group_name}** Balances\n"]
    for pid, data in balances.items():
        total = data["total"]
        sign = "+" if total > 0 else ""
        lines.append(
            f"- {directory.participant_name(pid)}: {sign}{format_money(total, directory.currency)}"
        )

    if reimbursements:
        lines.append("\n**Suggested Payments:**")
        for reimbursement in reimbursements:
            lines.append(format_reimbursement_text(reimbursement, directory, prefix="- "))
    return lines


def format_reimbursement_text(
    reimbursement: dict,
    directory: ParticipantDirectory,
    prefix: str = "",
) -> str:
    from_name = directory.participant_name(reimbursement["from"])
    to_name = directory.participant_name(reimbursement["to"])
    amount = format_money(reimbursement["amount"], directory.currency)
    return f"{prefix}{from_name} -> {to_name}: {amount}"


def format_settlement_option_label(reimbursement: dict, directory: ParticipantDirectory) -> str:
    from_name = directory.participant_name(reimbursement["from"])
    to_name = directory.participant_name(reimbursement["to"])
    amount = format_money(reimbursement["amount"], directory.currency)
    return f"{from_name} -> {to_name} ({amount})"


def format_settlement_line(index: int, reimbursement: dict, directory: ParticipantDirectory) -> str:
    from_name = html.escape(directory.participant_name(reimbursement["from"]))
    to_name = html.escape(directory.participant_name(reimbursement["to"]))
    amount = html.escape(format_money(reimbursement["amount"], directory.currency))
    return f"{index}. <b>{from_name}</b> owes <b>{to_name}</b> {amount}"
