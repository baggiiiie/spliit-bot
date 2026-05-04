from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Balance:
    participant_id: str
    total_cents: int


@dataclass(frozen=True, slots=True)
class Reimbursement:
    from_id: str
    to_id: str
    amount_cents: int


@dataclass(frozen=True, slots=True)
class BalanceReport:
    balances: list[Balance]
    reimbursements: list[Reimbursement]
