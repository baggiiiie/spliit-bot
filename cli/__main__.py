from __future__ import annotations

import argparse
import sys

from cli.format import format_reimbursement_text, format_settlement_option_label
from cli.target import resolve_cli_target
from domain import activity_label, format_activity_line_text, format_money, undoable_activity
from domain.dates import normalize_expense_date
from spliit_integration.gateway import NewExpense, Settlement, gateway


def group_cmd(group_id: str | None = None) -> int:
    resolved_group_id = resolve_cli_target(group_id)
    if not resolved_group_id:
        return 1

    group = gateway.group(resolved_group_id)
    print(f"{group.name} ({group.currency})")
    print()
    print("Participants:")
    for participant in group.directory.participants:
        print(f"- {participant.name}")
    return 0


def balance_cmd(group_id: str | None = None) -> int:
    resolved_group_id = resolve_cli_target(group_id)
    if not resolved_group_id:
        return 1

    group = gateway.group(resolved_group_id)
    directory = group.directory
    balance_report = gateway.balances(resolved_group_id)
    reimbursements = balance_report.reimbursements

    print(f"{group.name} balances")
    print()
    for balance in balance_report.balances:
        pid = balance.participant_id
        total = balance.total_cents
        sign = "+" if total > 0 else ""
        print(
            f"- {directory.participant_name(pid)}: {sign}{format_money(total, directory.currency)}"
        )

    if reimbursements:
        print()
        print("Suggested payments:")
        for reimbursement in reimbursements:
            print(format_reimbursement_text(reimbursement, directory, prefix="- "))

    return 0


def latest_cmd(limit: int, group_id: str | None = None) -> int:
    resolved_group_id = resolve_cli_target(group_id)
    if not resolved_group_id:
        return 1
    if limit < 1:
        print("Count must be a positive integer.", file=sys.stderr)
        return 1

    activities = gateway.activities(resolved_group_id, limit)
    if not activities:
        print("No activity found.")
        return 0

    print(f"Latest {len(activities)} activities")
    for index, activity in enumerate(activities, start=1):
        print(format_activity_line_text(activity, index))

    return 0


def add_cmd(
    title: str,
    amount: float,
    paid_by: str,
    participants: list[str],
    group_id: str | None = None,
    expense_date: str | None = None,
) -> int:
    resolved_group_id = resolve_cli_target(group_id)
    if not resolved_group_id:
        return 1

    directory = gateway.group(resolved_group_id).directory
    payer_id = directory.participant_id(paid_by)
    if not payer_id:
        print(f"Unknown participant: {paid_by}", file=sys.stderr)
        return 1

    unknown_names = directory.unknown_names(participants)
    if unknown_names:
        print(f"Unknown participant(s): {', '.join(unknown_names)}", file=sys.stderr)
        return 1

    payee_ids = [(payee_id, 1) for payee_id in directory.participant_ids(participants)]

    parsed_expense_date: str | None = None
    if expense_date:
        try:
            parsed_expense_date = normalize_expense_date(expense_date)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    gateway.create_expense(
        resolved_group_id,
        NewExpense(
            title=f"[cli] {title}",
            paid_by=payer_id,
            paid_for=payee_ids,
            amount_cents=round(amount * 100),
            expense_date=parsed_expense_date,
        ),
    )
    share = amount / len(participants)
    print(f"Added: {title}")
    print(f"Amount: {directory.currency}{amount:.2f}")
    if expense_date:
        print(f"Date: {expense_date}")
    print(f"Paid by: {paid_by}")
    print(f"Split ({directory.currency}{share:.2f} each): {', '.join(participants)}")
    return 0


def undo_cmd(index: int, assume_yes: bool, group_id: str | None = None) -> int:
    resolved_group_id = resolve_cli_target(group_id)
    if not resolved_group_id:
        return 1
    if index < 1:
        print("Count must be a positive integer.", file=sys.stderr)
        return 1

    activities = gateway.activities(resolved_group_id, index)
    if not activities:
        print("No activity found.")
        return 0
    if len(activities) < index:
        print(f"Only {len(activities)} activit{'y' if len(activities) == 1 else 'ies'} found.")
        return 1

    activity = activities[index - 1]
    undoable = undoable_activity(activity)
    if not undoable:
        print("This activity can't be undone. Only newly created expenses can be undone.")
        return 1
    expense_id, title = undoable

    if not assume_yes:
        response = input(f"Undo activity #{index}: {title}? [y/N] ").strip()
        if response.lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    gateway.delete_expense(resolved_group_id, expense_id)
    activity_type = activity.activity_type
    print("Undid:")
    print(f"- {activity_label(activity_type)}: {title}")
    return 0


def list_reimbursements(group_id: str | None = None) -> int:
    resolved_group_id = resolve_cli_target(group_id)
    if not resolved_group_id:
        return 1

    directory = gateway.group(resolved_group_id).directory
    balance_report = gateway.balances(resolved_group_id)
    reimbursements = balance_report.reimbursements
    if not reimbursements:
        print("No suggested reimbursements.")
        return 0

    for index, reimbursement in enumerate(reimbursements, start=1):
        print(f"{index}. {format_settlement_option_label(reimbursement, directory)}")

    return 0


def mark_reimbursement_paid(index: int, assume_yes: bool, group_id: str | None = None) -> int:
    resolved_group_id = resolve_cli_target(group_id)
    if not resolved_group_id:
        return 1

    directory = gateway.group(resolved_group_id).directory
    balance_report = gateway.balances(resolved_group_id)
    reimbursements = balance_report.reimbursements
    if not reimbursements:
        print("No suggested reimbursements.")
        return 1

    if index < 1 or index > len(reimbursements):
        print(f"Invalid reimbursement index: {index}", file=sys.stderr)
        return 1

    reimbursement = reimbursements[index - 1]
    from_id = reimbursement.from_id
    to_id = reimbursement.to_id
    amount = reimbursement.amount_cents
    settlement_display = format_settlement_option_label(reimbursement, directory)

    if not assume_yes:
        response = input(f"Mark as paid: {settlement_display}? [y/N] ").strip()
        if response.lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    gateway.settle(
        resolved_group_id,
        Settlement(from_id=from_id, to_id=to_id, amount_cents=amount),
    )
    print(f"Marked as paid: {settlement_display}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Spliit CLI")
    parser.add_argument(
        "--spliit-group",
        dest="spliit_group",
        help="Target Spliit group ID",
    )
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
    add_parser.add_argument(
        "--date",
        help="Expense date/time in ISO 8601, e.g. 2026-04-07 or 2026-04-07T21:21+08:00",
    )
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
        return group_cmd(args.spliit_group)
    if args.command == "balance":
        return balance_cmd(args.spliit_group)
    if args.command == "latest":
        return latest_cmd(args.limit, args.spliit_group)
    if args.command == "add":
        return add_cmd(
            args.title,
            args.amount,
            args.paid_by,
            args.participants,
            group_id=args.spliit_group,
            expense_date=args.date,
        )
    if args.command == "undo":
        return undo_cmd(args.index, args.yes, args.spliit_group)
    if args.command == "settle" and args.settle_command == "list":
        return list_reimbursements(args.spliit_group)
    if args.command == "settle" and args.settle_command == "pay":
        return mark_reimbursement_paid(args.index, args.yes, args.spliit_group)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
