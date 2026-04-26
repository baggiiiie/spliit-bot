"""Centralised constants, conversation states, pending-state dataclasses, and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SplitMode(StrEnum):
    """How an expense is split among payees.

    Mirrors Spliit's ``splitMode`` field. ``shares`` semantics in
    :data:`PaidFor` depend on the mode:

    - ``EVENLY``: shares ignored (always 1).
    - ``BY_SHARES``: integer share weights.
    - ``BY_PERCENTAGE``: shares = percent * 100 (sum = 10000).
    - ``BY_AMOUNT``: shares = exact cents per participant (sum = amount).
    """

    EVENLY = "EVENLY"
    BY_SHARES = "BY_SHARES"
    BY_PERCENTAGE = "BY_PERCENTAGE"
    BY_AMOUNT = "BY_AMOUNT"


# ---------------------------------------------------------------------------
# Callback data prefixes
# ---------------------------------------------------------------------------

CB_CONFIRM = "yes_"
CB_CANCEL = "no_"

CB_DEL_CONFIRM = "delyes_"
CB_DEL_CANCEL = "delno_"

CB_SETTLE = "settle_"
CB_SETTLE_CANCEL = "settleno_"

CB_SELECT_GROUP = "selgrp_"

CB_PAYER = "payer_"

CB_PAYEE = "payee_"
CB_PAYEE_DONE = "payee_done"
CB_PAYEE_ALL = "payee_all"

CB_SPLIT_MODE = "splitmode_"

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

TITLE, AMOUNT, PAYER, PAYEES, SELECT_GROUP, SPLIT_MODE, SPLIT_VALUES = range(7)

# ---------------------------------------------------------------------------
# Pending-state dataclasses
# ---------------------------------------------------------------------------

type PaidFor = list[tuple[str, int]]


@dataclass(slots=True)
class PendingExpense:
    title: str
    amount_cents: int
    payer_id: str
    paid_for: PaidFor
    tg_name: str
    group_id: str
    split_mode: SplitMode = SplitMode.EVENLY


@dataclass(slots=True)
class PendingDelete:
    expense_id: str
    group_id: str


@dataclass(slots=True)
class PendingSettlement:
    from_id: str
    to_id: str
    amount: int
    group_id: str


# ---------------------------------------------------------------------------
# Money formatting
# ---------------------------------------------------------------------------


def format_money(amount_cents: int, currency: str) -> str:
    return f"{currency}{amount_cents / 100:.2f}"
