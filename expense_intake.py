"""Expense draft intake policy for the /add flow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from constants import PaidFor, SplitMode
from expense_draft import ExpenseDraft, MissingExpenseField
from parsing import parse_add_command, parse_with_llm
from splits import parse_split_values


class IntakeField(StrEnum):
    TITLE = "title"
    AMOUNT = "amount"
    PAYER = "payer"
    PAYEES = "payees"
    SPLIT_MODE = "split_mode"
    SPLIT_VALUES = "split_values"


@dataclass(frozen=True, slots=True)
class LLMFailureReport:
    raw_text: str
    user_message: str
    raw_response: str | None


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
    admin_report: LLMFailureReport | None = None


@dataclass(frozen=True, slots=True)
class Ended:
    user_message: str | None = None


IntakeOutcome = NeedsInput | ReadyToConfirm | Rejected | Ended

FORMAT_HELP = "Format: `/add title, amount, names`"

_ADD_PREFIX_RE = re.compile(r"^/add[-_]?bill?\s*", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)")


def empty_draft_started(text: str) -> bool:
    command_text = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text else ""
    return command_text == "/add" and len(text.split(maxsplit=1)) == 1


def apply_title(draft: ExpenseDraft, text: str) -> IntakeOutcome:
    draft.title = text.strip()
    return next_prompt(draft)


def apply_amount(draft: ExpenseDraft, text: str) -> IntakeOutcome:
    match = _AMOUNT_RE.match(text.strip())
    if not match:
        return Rejected("Invalid amount. Enter a number:")
    draft.amount = float(match.group(1))
    return next_prompt(draft)


def apply_payer(draft: ExpenseDraft, payer_id: str) -> IntakeOutcome:
    draft.set_payer_id(payer_id)
    return next_prompt(draft)


def toggle_payee(draft: ExpenseDraft, payee_id: str) -> IntakeOutcome:
    draft.toggle_payee_id(payee_id)
    return NeedsInput(IntakeField.PAYEES)


def complete_payees(draft: ExpenseDraft) -> IntakeOutcome:
    if not draft.require_payees():
        return Rejected("Select at least one person")
    return next_prompt(draft)


def apply_split_mode(draft: ExpenseDraft, raw_split_mode: str) -> IntakeOutcome:
    try:
        split_mode = SplitMode(raw_split_mode)
    except ValueError:
        return NeedsInput(IntakeField.SPLIT_MODE)

    if split_mode is SplitMode.EVENLY:
        return ReadyToConfirm(split_mode=split_mode)

    draft.split_mode = split_mode
    return NeedsInput(IntakeField.SPLIT_VALUES)


def apply_split_values(draft: ExpenseDraft, text: str) -> IntakeOutcome:
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


async def start_from_text(
    text: str,
    participants_map: dict[str, str],
) -> tuple[ExpenseDraft, IntakeOutcome]:
    draft = ExpenseDraft.with_participants(participants_map)
    if empty_draft_started(text):
        return draft, NeedsInput(IntakeField.TITLE)

    participant_names = list(participants_map.keys())
    expense = parse_add_command(text, participant_names)

    raw_text = _ADD_PREFIX_RE.sub("", text, count=1).strip()
    if not expense:
        if not _should_try_llm(raw_text, participant_names):
            return draft, Ended(FORMAT_HELP)
        llm_result, raw_response = await parse_with_llm(raw_text, participant_names)
        if isinstance(llm_result, str):
            return draft, Rejected(
                llm_result,
                admin_report=LLMFailureReport(raw_text, llm_result, raw_response),
            )
        expense = llm_result

    if not expense:
        return draft, Ended(FORMAT_HELP)

    draft.apply_parsed(expense)
    return draft, next_prompt(draft)


def next_prompt(draft: ExpenseDraft) -> IntakeOutcome:
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


def _should_try_llm(raw_text: str, participant_names: list[str]) -> bool:
    has_number = bool(re.search(r"\d", raw_text))
    has_participant = any(n.lower() in raw_text.lower() for n in participant_names)
    return has_number or has_participant
