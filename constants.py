"""Centralised constants, conversation states, pending-state dataclasses, and helpers."""

from __future__ import annotations

from dataclasses import dataclass

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

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

TITLE, AMOUNT, PAYER, PAYEES, SELECT_GROUP = range(5)

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
