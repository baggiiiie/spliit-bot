from __future__ import annotations

from domain import ParticipantDirectory, format_money
from domain.balance import Reimbursement


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
