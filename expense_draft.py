"""Expense draft state for the Telegram /add flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from constants import CB_PAYEE_ALL, PaidFor, PendingExpense, SplitMode
from parsing import ParsedExpense


class MissingExpenseField(StrEnum):
    TITLE = "title"
    AMOUNT = "amount"
    PAYER = "payer"
    PAYEES = "payees"
    SPLIT_MODE = "split_mode"
    READY = "ready"


@dataclass(slots=True)
class ExpenseDraft:
    title: str | None = None
    amount: float | None = None
    payer_id: str | None = None
    payer_name: str | None = None
    payee_ids: list[str] = field(default_factory=list)
    participants_map: dict[str, str] = field(default_factory=dict)
    split_mode: SplitMode | None = None

    @classmethod
    def with_participants(cls, participants_map: dict[str, str]) -> ExpenseDraft:
        return cls(participants_map=participants_map)

    def apply_parsed(self, expense: ParsedExpense) -> None:
        if expense.title:
            self.title = expense.title
        if expense.amount:
            self.amount = expense.amount
        if expense.payer:
            self.payer_id = self.participants_map[expense.payer]
            self.payer_name = expense.payer
        if expense.participants:
            name_map = {name.lower(): pid for name, pid in self.participants_map.items()}
            self.payee_ids = [
                pid for name in expense.participants if (pid := name_map.get(name.lower()))
            ]

    def set_payer_id(self, payer_id: str) -> None:
        reverse = self.id_to_name()
        self.payer_id = payer_id
        self.payer_name = reverse[payer_id]

    def toggle_payee_id(self, payee_id: str) -> None:
        if payee_id == CB_PAYEE_ALL:
            all_ids = list(self.participants_map.values())
            self.payee_ids = [] if set(self.payee_ids) == set(all_ids) else all_ids
        elif payee_id in self.payee_ids:
            self.payee_ids.remove(payee_id)
        else:
            self.payee_ids.append(payee_id)

    def require_payees(self) -> bool:
        return bool(self.payee_ids)

    def id_to_name(self) -> dict[str, str]:
        return {pid: name for name, pid in self.participants_map.items()}

    def payee_names(self) -> list[str]:
        reverse = self.id_to_name()
        return [reverse[pid] for pid in self.payee_ids]

    def next_missing_field(self) -> MissingExpenseField:
        if not self.title:
            return MissingExpenseField.TITLE
        if not self.amount:
            return MissingExpenseField.AMOUNT
        if not self.payer_id:
            return MissingExpenseField.PAYER
        if not self.payee_ids:
            return MissingExpenseField.PAYEES
        if not self.split_mode:
            return MissingExpenseField.SPLIT_MODE
        return MissingExpenseField.READY

    def to_pending_expense(
        self,
        tg_name: str,
        group_id: str,
        split_mode: SplitMode,
        paid_for: PaidFor | None = None,
    ) -> PendingExpense:
        assert self.title is not None
        assert self.amount is not None
        assert self.payer_id is not None
        return PendingExpense(
            title=self.title,
            amount_cents=int(self.amount * 100),
            payer_id=self.payer_id,
            paid_for=paid_for or [(pid, 1) for pid in self.payee_ids],
            tg_name=tg_name,
            group_id=group_id,
            split_mode=split_mode,
        )


DRAFT_KEY = "expense_draft"


def get_draft(user_data: dict) -> ExpenseDraft:
    draft = user_data.get(DRAFT_KEY)
    assert isinstance(draft, ExpenseDraft)
    return draft


def set_draft(user_data: dict, draft: ExpenseDraft) -> None:
    user_data[DRAFT_KEY] = draft


def clear_draft(user_data: dict) -> None:
    user_data.pop(DRAFT_KEY, None)
