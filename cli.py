from __future__ import annotations

import argparse
import sys
from typing import Any

from config import SPLIIT_GROUP_ID, spliit
from helpers import id_to_name_map
from services import delete_expense, get_activities, get_balances, settle_reimbursement

ACTIVITY_LABELS = {
    "CREATE_EXPENSE": "Created expense",
    "UPDATE_EXPENSE": "Updated expense",
    "DELETE_EXPENSE": "Deleted expense",
    "UPDATE_GROUP": "Updated group",
}


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
    if limit < 1:
        print("Count must be a positive integer.", file=sys.stderr)
        return 1

    activities = get_activities(SPLIIT_GROUP_ID, limit)
    if not activities:
        print("No activity found.")
        return 0

    print(f"Latest {len(activities)} activities")
    for index, activity in enumerate(activities, start=1):
        label = ACTIVITY_LABELS.get(activity["activityType"], activity["activityType"])
        print(f"{index}. {label}: {_activity_subject(activity)}")

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


def _activity_subject(activity: dict[str, Any]) -> str:
    if data := activity.get("data"):
        return str(data)
    if isinstance(activity.get("expense"), dict):
        expense = activity["expense"]
        title = expense.get("title")
        if title:
            return str(title)
    return "Untitled"


def _undoable_activity(activity: dict[str, Any]) -> tuple[str, str] | None:
    if activity.get("activityType") != "CREATE_EXPENSE":
        return None
    expense_id = activity.get("expenseId")
    if not expense_id or not activity.get("expense"):
        return None
    return str(expense_id), _activity_subject(activity)


def undo_cmd(index: int, assume_yes: bool) -> int:
    if (code := _require_spliit()) is not None:
        return code
    if index < 1:
        print("Count must be a positive integer.", file=sys.stderr)
        return 1

    activities = get_activities(SPLIIT_GROUP_ID, index)
    if not activities:
        print("No activity found.")
        return 0
    if len(activities) < index:
        print(f"Only {len(activities)} activit{'y' if len(activities) == 1 else 'ies'} found.")
        return 1

    activity = activities[index - 1]
    undoable = _undoable_activity(activity)
    if not undoable:
        print("This activity can't be undone. Only newly created expenses can be undone.")
        return 1
    expense_id, title = undoable

    if not assume_yes:
        response = input(f"Undo activity #{index}: {title}? [y/N] ").strip()
        if response.lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    delete_expense(SPLIIT_GROUP_ID, expense_id)
    label = ACTIVITY_LABELS.get(str(activity["activityType"]), str(activity["activityType"]))
    print("Undid:")
    print(f"- {label}: {title}")
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

    latest_parser = subparsers.add_parser("latest", help="Show recent activity")
    latest_parser.add_argument(
        "limit", nargs="?", type=int, default=5, help="How many activities to show"
    )

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

    undo_parser = subparsers.add_parser("undo", help="Undo a recent activity")
    undo_parser.add_argument(
        "index", nargs="?", type=int, default=1, help="1-based activity index from `latest`"
    )
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
        return undo_cmd(args.index, args.yes)
    if args.command == "settle" and args.settle_command == "list":
        return list_reimbursements()
    if args.command == "settle" and args.settle_command == "pay":
        return mark_reimbursement_paid(args.index, args.yes)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
