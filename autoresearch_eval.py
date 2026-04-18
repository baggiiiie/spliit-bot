from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass

from parsing import ParsedExpense, parse_with_llm

PARTICIPANTS = ["Baggie", "Neo", "Yoga", "Ricky"]


@dataclass(frozen=True)
class EvalCase:
    name: str
    message: str
    expected: ParsedExpense | None
    is_expense: bool
    tool_ready: bool = False


@dataclass(frozen=True)
class EvalResult:
    name: str
    success: bool
    field_matches: int
    field_total: int
    false_positive: int
    tool_ready_success: int
    tool_ready_total: int
    raw_response: str | None
    parsed: str | None | dict[str, object]
    expected: dict[str, object] | None
    comparisons: dict[str, bool] | None = None


CASES = [
    EvalCase(
        name="payer_first_with_with",
        message="baggie paid 32 for ikea lunch with ricky",
        expected=ParsedExpense(
            title="ikea lunch",
            amount=32.0,
            payer="Baggie",
            participants=["baggie", "ricky"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="split_between_phrase",
        message="dinner cost 100 split between baggie and neo, baggie paid",
        expected=ParsedExpense(
            title="dinner",
            amount=100.0,
            payer="Baggie",
            participants=["baggie", "neo"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="payer_covered_for_subset",
        message="neo covered grab 18.6 for neo and yoga",
        expected=ParsedExpense(
            title="grab",
            amount=18.6,
            payer="Neo",
            participants=["neo", "yoga"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="amount_first_payer_last",
        message=("please add 45.20 for board games split across baggie neo yoga ricky, yoga paid"),
        expected=ParsedExpense(
            title="board games",
            amount=45.2,
            payer="Yoga",
            participants=["baggie", "neo", "yoga", "ricky"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="everyone_without_payer",
        message="lunch 50 everyone splits",
        expected=ParsedExpense(
            title="lunch",
            amount=50.0,
            payer=None,
            participants=["baggie", "neo", "yoga", "ricky"],
        ),
        is_expense=True,
    ),
    EvalCase(
        name="paid_by_phrase",
        message="add movie tickets 27.5 paid by yoga for baggie and yoga",
        expected=ParsedExpense(
            title="movie tickets",
            amount=27.5,
            payer="Yoga",
            participants=["baggie", "yoga"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="all_of_us_phrase",
        message="ricky bought snacks for 14.90 for all of us",
        expected=ParsedExpense(
            title="snacks",
            amount=14.9,
            payer="Ricky",
            participants=["baggie", "neo", "yoga", "ricky"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="explicit_split_with",
        message="uber home 22, neo paid, split with baggie and neo",
        expected=ParsedExpense(
            title="uber home",
            amount=22.0,
            payer="Neo",
            participants=["baggie", "neo"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="self_only",
        message="baggie spent 9.5 on boba for baggie",
        expected=ParsedExpense(
            title="boba",
            amount=9.5,
            payer="Baggie",
            participants=["baggie"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="subset_without_payer_in_title",
        message="taxi 30 for neo and ricky, ricky paid",
        expected=ParsedExpense(
            title="taxi",
            amount=30.0,
            payer="Ricky",
            participants=["neo", "ricky"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="covered_it_phrase",
        message="brunch was 64.80 and yoga covered it for baggie, neo, yoga",
        expected=ParsedExpense(
            title="brunch",
            amount=64.8,
            payer="Yoga",
            participants=["baggie", "neo", "yoga"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="missing_payer",
        message="coffee 12 split with neo and ricky",
        expected=ParsedExpense(
            title="coffee",
            amount=12.0,
            payer=None,
            participants=["neo", "ricky"],
        ),
        is_expense=True,
    ),
    EvalCase(
        name="split_among_phrase",
        message="please add dessert 16.8, neo paid, split among baggie neo yoga",
        expected=ParsedExpense(
            title="dessert",
            amount=16.8,
            payer="Neo",
            participants=["baggie", "neo", "yoga"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="everyone_with_explicit_payer",
        message="ricky covered airport taxi 41 for everyone",
        expected=ParsedExpense(
            title="airport taxi",
            amount=41.0,
            payer="Ricky",
            participants=["baggie", "neo", "yoga", "ricky"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="only_subset_splitting",
        message="booked mahjong room 88, paid by yoga, only yoga and neo splitting",
        expected=ParsedExpense(
            title="mahjong room",
            amount=88.0,
            payer="Yoga",
            participants=["neo", "yoga"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="single_participant_without_payer",
        message="add coffee beans 14 for baggie only",
        expected=ParsedExpense(
            title="coffee beans",
            amount=14.0,
            payer=None,
            participants=["baggie"],
        ),
        is_expense=True,
    ),
    EvalCase(
        name="plus_sign_participants",
        message="neo bought fries 6.5 for neo + ricky",
        expected=ParsedExpense(
            title="fries",
            amount=6.5,
            payer="Neo",
            participants=["neo", "ricky"],
        ),
        is_expense=True,
        tool_ready=True,
    ),
    EvalCase(
        name="shared_by_without_payer",
        message="movie 28 shared by neo and yoga",
        expected=ParsedExpense(
            title="movie",
            amount=28.0,
            payer=None,
            participants=["neo", "yoga"],
        ),
        is_expense=True,
    ),
    EvalCase(name="greeting", message="hello how are you", expected=None, is_expense=False),
    EvalCase(
        name="balance_question",
        message="what's the group balance?",
        expected=None,
        is_expense=False,
    ),
    EvalCase(
        name="money_question_not_expense",
        message="who owes 20 right now?",
        expected=None,
        is_expense=False,
    ),
    EvalCase(
        name="undo_command",
        message="undo the last expense",
        expected=None,
        is_expense=False,
    ),
    EvalCase(name="group_question", message="who is in the group", expected=None, is_expense=False),
]


def _norm_title(value: str | None) -> str | None:
    return " ".join(value.lower().split()) if value else None


def _norm_payer(value: str | None) -> str | None:
    return value.lower() if value else None


def _norm_participants(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    return sorted({name.lower() for name in value})


async def _run_case(case: EvalCase) -> EvalResult:
    result, raw_response = await parse_with_llm(case.message, PARTICIPANTS)

    if not case.is_expense:
        success = isinstance(result, str) or result is None
        parsed = asdict(result) if isinstance(result, ParsedExpense) else result
        return EvalResult(
            name=case.name,
            success=success,
            field_matches=int(success),
            field_total=1,
            false_positive=int(not success),
            tool_ready_success=0,
            tool_ready_total=0,
            raw_response=raw_response,
            parsed=parsed,
            expected=None,
        )

    expected = case.expected
    assert expected is not None
    parsed_expense = result if isinstance(result, ParsedExpense) else ParsedExpense()

    comparisons = {
        "title": _norm_title(parsed_expense.title) == _norm_title(expected.title),
        "amount": parsed_expense.amount == expected.amount,
        "payer": _norm_payer(parsed_expense.payer) == _norm_payer(expected.payer),
        "participants": _norm_participants(parsed_expense.participants)
        == _norm_participants(expected.participants),
    }
    field_matches = sum(int(match) for match in comparisons.values())
    success = field_matches == 4

    return EvalResult(
        name=case.name,
        success=success,
        field_matches=field_matches,
        field_total=4,
        false_positive=0,
        tool_ready_success=int(success and case.tool_ready),
        tool_ready_total=int(case.tool_ready),
        raw_response=raw_response,
        parsed=asdict(parsed_expense),
        expected=asdict(expected),
        comparisons=comparisons,
    )


async def _main(verbose: bool) -> int:
    results: list[EvalResult] = []
    for case in CASES:
        results.append(await _run_case(case))

    success_count = sum(int(result.success) for result in results)
    field_matches = sum(result.field_matches for result in results)
    field_total = sum(result.field_total for result in results)
    false_positive_count = sum(result.false_positive for result in results)
    tool_ready_success = sum(result.tool_ready_success for result in results)
    tool_ready_total = sum(result.tool_ready_total for result in results)

    pass_rate = 100.0 * success_count / len(CASES)
    field_rate = 100.0 * field_matches / field_total
    tool_ready_rate = 100.0 * tool_ready_success / tool_ready_total

    if verbose:
        for case, result in zip(CASES, results, strict=True):
            if result.success:
                continue
            print(f"[FAIL] {case.name}: {case.message}")
            print(json.dumps(asdict(result), indent=2, sort_keys=True))

    summary = {
        "cases": len(CASES),
        "success_count": success_count,
        "pass_rate": round(pass_rate, 2),
        "field_rate": round(field_rate, 2),
        "tool_ready_rate": round(tool_ready_rate, 2),
        "false_positive_count": false_positive_count,
    }
    print(json.dumps(summary, sort_keys=True))
    print(f"METRIC pass_rate={pass_rate:.2f}")
    print(f"METRIC field_rate={field_rate:.2f}")
    print(f"METRIC tool_ready_rate={tool_ready_rate:.2f}")
    print(f"METRIC false_positive_count={false_positive_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate prompt-driven expense extraction")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-case failure details")
    args = parser.parse_args()
    return asyncio.run(_main(verbose=not args.quiet))


if __name__ == "__main__":
    raise SystemExit(main())
