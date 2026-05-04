"""Pure expense draft state machine for the Telegram /add flow."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from domain.split import PaidFor, SplitMode, parse_split_values


@dataclass(frozen=True, slots=True)
class LLMParsedExpense:
    title: str | None = None
    amount: float | None = None
    payer: str | None = None
    participants: list[str] | None = None


@dataclass(frozen=True, slots=True)
class ParseFailure:
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


class MissingExpenseField(StrEnum):
    TITLE = "title"
    AMOUNT = "amount"
    PAYER = "payer"
    PAYEES = "payees"
    SPLIT_MODE = "split_mode"
    READY = "ready"


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
IntakeOutcome = Outcome
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
    match draft.next_missing_field():
        case MissingExpenseField.TITLE:
            return NeedsInput(IntakeField.TITLE)
        case MissingExpenseField.AMOUNT:
            return NeedsInput(IntakeField.AMOUNT)
        case MissingExpenseField.PAYER:
            return NeedsInput(IntakeField.PAYER)
        case MissingExpenseField.PAYEES:
            return NeedsInput(IntakeField.PAYEES)
        case MissingExpenseField.SPLIT_MODE | MissingExpenseField.READY:
            return NeedsInput(IntakeField.SPLIT_MODE)


@dataclass(frozen=True, slots=True)
class StartInput:
    pass


@dataclass(frozen=True, slots=True)
class LLMParsedExpenseInput:
    expense: LLMParsedExpense
    participants_map: dict[str, str]


@dataclass(frozen=True, slots=True)
class TitleInput:
    text: str


@dataclass(frozen=True, slots=True)
class AmountInput:
    text: str


@dataclass(frozen=True, slots=True)
class PayerInput:
    payer_id: str


@dataclass(frozen=True, slots=True)
class PayeeToggleInput:
    payee_id: str


@dataclass(frozen=True, slots=True)
class PayeesToggleAllInput:
    pass


@dataclass(frozen=True, slots=True)
class PayeesDoneInput:
    pass


@dataclass(frozen=True, slots=True)
class SplitModeInput:
    raw_split_mode: str


@dataclass(frozen=True, slots=True)
class SplitValuesInput:
    text: str


DraftInput = (
    StartInput
    | LLMParsedExpenseInput
    | TitleInput
    | AmountInput
    | PayerInput
    | PayeeToggleInput
    | PayeesToggleAllInput
    | PayeesDoneInput
    | SplitModeInput
    | SplitValuesInput
)


async def apply(
    draft: ExpenseDraft | None,
    draft_input: DraftInput,
) -> tuple[ExpenseDraft, Outcome]:
    if isinstance(draft_input, StartInput):
        return start_draft()
    if isinstance(draft_input, LLMParsedExpenseInput):
        return start_from_parsed(draft_input.expense, draft_input.participants_map)

    assert draft is not None
    if isinstance(draft_input, TitleInput):
        outcome = apply_title(draft, draft_input.text)
    elif isinstance(draft_input, AmountInput):
        outcome = apply_amount(draft, draft_input.text)
    elif isinstance(draft_input, PayerInput):
        outcome = apply_payer(draft, draft_input.payer_id)
    elif isinstance(draft_input, PayeeToggleInput):
        outcome = toggle_payee(draft, draft_input.payee_id)
    elif isinstance(draft_input, PayeesToggleAllInput):
        outcome = toggle_all_payees(draft)
    elif isinstance(draft_input, PayeesDoneInput):
        outcome = complete_payees(draft)
    elif isinstance(draft_input, SplitModeInput):
        outcome = apply_split_mode(draft, draft_input.raw_split_mode)
    elif isinstance(draft_input, SplitValuesInput):
        outcome = apply_split_values(draft, draft_input.text)
    else:
        raise AssertionError("unreachable draft input")
    return draft, outcome
