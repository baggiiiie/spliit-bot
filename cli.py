from __future__ import annotations

import argparse
import sys

from config import SPLIIT_GROUP_ID, spliit
from helpers import id_to_name_map
from services import delete_expense, get_balances, get_expenses, settle_reimbursement


def _require_spliit() -> int | None:
    if spliit:
        return None
    print("SPLIIT_GROUP_ID not configured.", file=sys.stderr)
    return 1


def _participant_maps() -> tuple[dict[str, str], dict[str, str], str]:
    assert spliit
    id_name, currency = id_to_name_map(spliit)
    name_id = {name.lower(): pid for pid, name in id_name.items()}
    return id_name, name_id, currency


def group_cmd() -> int:
    if (code := _require_spliit()) is not None:
        return code

    assert spliit
    group = spliit.get_group()
    print(f"{group['name']} ({group['currency']})")
    print()
    print("Participants:")
    for participant in group["participants"]:
        print(f"- {participant['name']}")
    return 0


def balance_cmd() -> int:
    if (code := _require_spliit()) is not None:
        return code

    assert spliit
    id_name, currency = id_to_name_map(spliit)
    balance_data = get_balances(SPLIIT_GROUP_ID)
    balances = balance_data["balances"]
    reimbursements = balance_data["reimbursements"]
    group = spliit.get_group()

    print(f"{group['name']} balances")
    print()
    for pid, data in balances.items():
        total = data["total"] / 100
        sign = "+" if total > 0 else ""
        print(f"- {id_name.get(pid, pid)}: {sign}{currency}{total:.2f}")

    if reimbursements:
        print()
        print("Suggested payments:")
        for reimbursement in reimbursements:
            from_name = id_name.get(reimbursement["from"], reimbursement["from"])
            to_name = id_name.get(reimbursement["to"], reimbursement["to"])
            amount = reimbursement["amount"] / 100
            print(f"- {from_name} -> {to_name}: {currency}{amount:.2f}")

    return 0


def latest_cmd(limit: int) -> int:
    if (code := _require_spliit()) is not None:
        return code

    _, _, currency = _participant_maps()
    expenses = get_expenses(SPLIIT_GROUP_ID)
    if not expenses:
        print("No expenses found.")
        return 0

    print(f"Latest {min(limit, len(expenses))} expenses")
    for expense in expenses[:limit]:
        amount = expense["amount"] / 100
        payee_names = [participant["participant"]["name"] for participant in expense["paidFor"]]
        print()
        print(f"- {expense['title']}")
        print(f"  Amount: {currency}{amount:.2f}")
        print(f"  Paid by: {expense['paidBy']['name']}")
        print(f"  Split: {', '.join(payee_names)}")

    return 0


def add_cmd(title: str, amount: float, paid_by: str, participants: list[str]) -> int:
    if (code := _require_spliit()) is not None:
        return code

    _, name_id, currency = _participant_maps()
    payer_id = name_id.get(paid_by.lower())
    if not payer_id:
        print(f"Unknown participant: {paid_by}", file=sys.stderr)
        return 1

    payee_ids: list[tuple[str, int]] = []
    unknown_names = [name for name in participants if name.lower() not in name_id]
    if unknown_names:
        print(f"Unknown participant(s): {', '.join(unknown_names)}", file=sys.stderr)
        return 1

    for name in participants:
        payee_ids.append((name_id[name.lower()], 1))

    assert spliit
    spliit.add_expense(
        title=f"[cli] {title}",
        paid_by=payer_id,
        paid_for=payee_ids,
        amount=round(amount * 100),
    )
    share = amount / len(participants)
    print(f"Added: {title}")
    print(f"Amount: {currency}{amount:.2f}")
    print(f"Paid by: {paid_by}")
    print(f"Split ({currency}{share:.2f} each): {', '.join(participants)}")
    return 0


def undo_cmd(assume_yes: bool) -> int:
    if (code := _require_spliit()) is not None:
        return code

    expenses = get_expenses(SPLIIT_GROUP_ID)
    if not expenses:
        print("No expenses found.")
        return 0

    _, _, currency = _participant_maps()
    latest = expenses[0]
    title = latest["title"]
    amount = latest["amount"] / 100
    payer_name = latest["paidBy"]["name"]
    payee_names = [participant["participant"]["name"] for participant in latest["paidFor"]]

    if not assume_yes:
        response = input(f"Delete latest expense: {title} ({currency}{amount:.2f})? [y/N] ").strip()
        if response.lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    delete_expense(SPLIIT_GROUP_ID, latest["id"])
    print("Deleted:")
    print(f"- {title}")
    print(f"  Amount: {currency}{amount:.2f}")
    print(f"  Paid by: {payer_name}")
    print(f"  Split: {', '.join(payee_names)}")
    return 0


def list_reimbursements() -> int:
    if (code := _require_spliit()) is not None:
        return code

    id_name, _, currency = _participant_maps()
    reimbursements = get_balances(SPLIIT_GROUP_ID)["reimbursements"]
    if not reimbursements:
        print("No suggested reimbursements.")
        return 0

    for index, reimbursement in enumerate(reimbursements, start=1):
        from_name = id_name.get(reimbursement["from"], reimbursement["from"])
        to_name = id_name.get(reimbursement["to"], reimbursement["to"])
        amount = reimbursement["amount"] / 100
        print(f"{index}. {from_name} -> {to_name} ({currency}{amount:.2f})")

    return 0


def mark_reimbursement_paid(index: int, assume_yes: bool) -> int:
    if (code := _require_spliit()) is not None:
        return code

    id_name, _, currency = _participant_maps()
    reimbursements = get_balances(SPLIIT_GROUP_ID)["reimbursements"]
    if not reimbursements:
        print("No suggested reimbursements.")
        return 1

    if index < 1 or index > len(reimbursements):
        print(f"Invalid reimbursement index: {index}", file=sys.stderr)
        return 1

    reimbursement = reimbursements[index - 1]
    from_id = reimbursement["from"]
    to_id = reimbursement["to"]
    amount = reimbursement["amount"]
    from_name = id_name.get(from_id, from_id)
    to_name = id_name.get(to_id, to_id)
    amount_display = amount / 100

    if not assume_yes:
        response = input(
            f"Mark as paid: {from_name} -> {to_name} ({currency}{amount_display:.2f})? [y/N] "
        ).strip()
        if response.lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    settle_reimbursement(SPLIIT_GROUP_ID, from_id, to_id, amount)
    print(f"Marked as paid: {from_name} -> {to_name} ({currency}{amount_display:.2f})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Spliit CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("group", help="Show participants")
    subparsers.add_parser("balance", help="Show balances and suggested reimbursements")

    latest_parser = subparsers.add_parser("latest", help="Show recent expenses")
    latest_parser.add_argument("--limit", type=int, default=5, help="How many expenses to show")

    add_parser = subparsers.add_parser("add", help="Add an expense")
    add_parser.add_argument("title", help="Expense title")
    add_parser.add_argument("amount", type=float, help="Expense amount in group currency")
    add_parser.add_argument("--paid-by", required=True, help="Participant who paid")
    add_parser.add_argument(
        "--with",
        dest="participants",
        nargs="+",
        required=True,
        help="Participants included in the split",
    )

    undo_parser = subparsers.add_parser("undo", help="Delete the latest expense")
    undo_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    settle_parser = subparsers.add_parser("settle", help="List or settle suggested reimbursements")
    settle_subparsers = settle_parser.add_subparsers(dest="settle_command", required=True)

    settle_subparsers.add_parser("list", help="List suggested reimbursements")

    pay_parser = settle_subparsers.add_parser("pay", help="Mark a reimbursement as paid")
    pay_parser.add_argument(
        "index", type=int, help="1-based reimbursement index from `settle list`"
    )
    pay_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "group":
        return group_cmd()
    if args.command == "balance":
        return balance_cmd()
    if args.command == "latest":
        return latest_cmd(args.limit)
    if args.command == "add":
        return add_cmd(args.title, args.amount, args.paid_by, args.participants)
    if args.command == "undo":
        return undo_cmd(args.yes)
    if args.command == "settle" and args.settle_command == "list":
        return list_reimbursements()
    if args.command == "settle" and args.settle_command == "pay":
        return mark_reimbursement_paid(args.index, args.yes)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
