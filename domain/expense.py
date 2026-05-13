"""Pure expense draft state machine for the Telegram /add flow."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from domain.split import PaidFor, SplitMode, parse_split_values


class LLMParsedExpense(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None = None
    amount: float | None = None
    payer: str | None = None
    participants: list[str] | None = None


class ParseFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_message: str
    raw_response: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmedExpense:
    title: str
    amount_cents: int
    payer_id: str
    paid_for: PaidFor
    split_mode: SplitMode


@dataclass(slots=True)
class PendingExpense:
    expense: ConfirmedExpense
    tg_name: str
    group_id: str


class IntakeField(StrEnum):
    TITLE = "title"
    AMOUNT = "amount"
    PAYER = "payer"
    PAYEES = "payees"
    SPLIT_MODE = "split_mode"
    SPLIT_VALUES = "split_values"


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

    def apply_parsed(self, expense: LLMParsedExpense) -> None:
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
        if payee_id in self.payee_ids:
            self.payee_ids.remove(payee_id)
        else:
            self.payee_ids.append(payee_id)

    def toggle_all_payees(self) -> None:
        all_ids = list(self.participants_map.values())
        self.payee_ids = [] if set(self.payee_ids) == set(all_ids) else all_ids

    def require_payees(self) -> bool:
        return bool(self.payee_ids)

    def id_to_name(self) -> dict[str, str]:
        return {pid: name for name, pid in self.participants_map.items()}

    def payee_names(self) -> list[str]:
        reverse = self.id_to_name()
        return [reverse[pid] for pid in self.payee_ids]

    def confirm(
        self,
        split_mode: SplitMode,
        paid_for: PaidFor | None = None,
    ) -> ConfirmedExpense:
        assert self.title is not None
        assert self.amount is not None
        assert self.payer_id is not None
        return ConfirmedExpense(
            title=self.title,
            amount_cents=int(self.amount * 100),
            payer_id=self.payer_id,
            paid_for=paid_for or [(pid, 1) for pid in self.payee_ids],
            split_mode=split_mode,
        )


@dataclass(frozen=True, slots=True)
class NeedsInput:
    field: IntakeField


@dataclass(frozen=True, slots=True)
class ReadyToConfirm:
    split_mode: SplitMode
    paid_for: PaidFor | None = None


@dataclass(frozen=True, slots=True)
class Rejected:
    user_message: str


@dataclass(frozen=True, slots=True)
class Ended:
    user_message: str | None = None


Outcome = NeedsInput | ReadyToConfirm | Rejected | Ended
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)")


def start_draft() -> tuple[ExpenseDraft, Outcome]:
    draft = ExpenseDraft()
    return draft, NeedsInput(IntakeField.TITLE)


def start_from_parsed(
    expense: LLMParsedExpense,
    participants_map: dict[str, str],
) -> tuple[ExpenseDraft, Outcome]:
    draft = ExpenseDraft.with_participants(participants_map)
    draft.apply_parsed(expense)
    return draft, next_prompt(draft)


def apply_title(draft: ExpenseDraft, text: str) -> Outcome:
    draft.title = text.strip()
    return next_prompt(draft)


def apply_amount(draft: ExpenseDraft, text: str) -> Outcome:
    match = _AMOUNT_RE.match(text.strip())
    if not match:
        return Rejected("Invalid amount. Enter a number:")
    draft.amount = float(match.group(1))
    return next_prompt(draft)


def apply_payer(draft: ExpenseDraft, payer_id: str) -> Outcome:
    draft.set_payer_id(payer_id)
    return next_prompt(draft)


def toggle_payee(draft: ExpenseDraft, payee_id: str) -> Outcome:
    draft.toggle_payee_id(payee_id)
    return NeedsInput(IntakeField.PAYEES)


def toggle_all_payees(draft: ExpenseDraft) -> Outcome:
    draft.toggle_all_payees()
    return NeedsInput(IntakeField.PAYEES)


def complete_payees(draft: ExpenseDraft) -> Outcome:
    if not draft.require_payees():
        return Rejected("Select at least one person")
    return next_prompt(draft)


def apply_split_mode(draft: ExpenseDraft, raw_split_mode: str) -> Outcome:
    try:
        split_mode = SplitMode(raw_split_mode)
    except ValueError:
        return NeedsInput(IntakeField.SPLIT_MODE)

    if split_mode is SplitMode.EVENLY:
        return ReadyToConfirm(split_mode=split_mode)

    draft.split_mode = split_mode
    return NeedsInput(IntakeField.SPLIT_VALUES)


def apply_split_values(draft: ExpenseDraft, text: str) -> Outcome:
    if not draft.split_mode:
        return Ended()
    assert draft.amount is not None
    paid_for, error = parse_split_values(
        text.strip(),
        draft.payee_ids,
        draft.payee_names(),
        draft.split_mode,
        int(draft.amount * 100),
    )
    if error:
        return Rejected(f"{error}\nTry again:")
    return ReadyToConfirm(split_mode=draft.split_mode, paid_for=paid_for)


def next_prompt(draft: ExpenseDraft) -> Outcome:
    if not draft.title:
        return NeedsInput(IntakeField.TITLE)
    if not draft.amount:
        return NeedsInput(IntakeField.AMOUNT)
    if not draft.payer_id:
        return NeedsInput(IntakeField.PAYER)
    if not draft.payee_ids:
        return NeedsInput(IntakeField.PAYEES)
    return NeedsInput(IntakeField.SPLIT_MODE)
