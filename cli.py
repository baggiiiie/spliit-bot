from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from spliit import Spliit

from config import get_spliit
from domain import activity_label, activity_subject, id_to_name_map, undoable_activity
from services import (
    create_expense,
    delete_expense,
    get_activities,
    get_balances,
    settle_reimbursement,
)


def _resolve_target(group_id: str | None) -> tuple[str, Spliit] | None:
    if not group_id:
        print("Missing required --spliit-group.", file=sys.stderr)
        return None
    return group_id, get_spliit(group_id)


def _participant_maps(client: Spliit) -> tuple[dict[str, str], dict[str, str], str]:
    id_name, currency = id_to_name_map(client)
    name_id = {name.lower(): pid for pid, name in id_name.items()}
    return id_name, name_id, currency


def group_cmd(group_id: str | None = None) -> int:
    resolved = _resolve_target(group_id)
    if not resolved:
        return 1
    _group_id, client = resolved

    group = client.get_group()
    print(f"{group['name']} ({group['currency']})")
    print()
    print("Participants:")
    for participant in group["participants"]:
        print(f"- {participant['name']}")
    return 0


def balance_cmd(group_id: str | None = None) -> int:
    resolved = _resolve_target(group_id)
    if not resolved:
        return 1
    resolved_group_id, client = resolved

    id_name, currency = id_to_name_map(client)
    balance_data = get_balances(resolved_group_id)
    balances = balance_data["balances"]
    reimbursements = balance_data["reimbursements"]
    group = client.get_group()

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


def latest_cmd(limit: int, group_id: str | None = None) -> int:
    resolved = _resolve_target(group_id)
    if not resolved:
        return 1
    resolved_group_id, _client = resolved
    if limit < 1:
        print("Count must be a positive integer.", file=sys.stderr)
        return 1

    activities = get_activities(resolved_group_id, limit)
    if not activities:
        print("No activity found.")
        return 0

    print(f"Latest {len(activities)} activities")
    for index, activity in enumerate(activities, start=1):
        label = activity_label(str(activity["activityType"]))
        subject = activity_subject(activity)
        print(f"{index}. {label}: {subject}")

    return 0


def _parse_expense_date(value: str) -> str:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "Invalid --date. Use ISO 8601, e.g. 2026-04-07, "
            "2026-04-07T21:21, or 2026-04-07T21:21+08:00."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def add_cmd(
    title: str,
    amount: float,
    paid_by: str,
    participants: list[str],
    group_id: str | None = None,
    expense_date: str | None = None,
) -> int:
    resolved = _resolve_target(group_id)
    if not resolved:
        return 1
    _resolved_group_id, client = resolved

    _, name_id, currency = _participant_maps(client)
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

    parsed_expense_date: str | None = None
    if expense_date:
        try:
            parsed_expense_date = _parse_expense_date(expense_date)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    create_expense(
        group_id=_resolved_group_id,
        title=f"[cli] {title}",
        paid_by=payer_id,
        paid_for=payee_ids,
        amount=round(amount * 100),
        expense_date=parsed_expense_date,
    )
    share = amount / len(participants)
    print(f"Added: {title}")
    print(f"Amount: {currency}{amount:.2f}")
    if expense_date:
        print(f"Date: {expense_date}")
    print(f"Paid by: {paid_by}")
    print(f"Split ({currency}{share:.2f} each): {', '.join(participants)}")
    return 0


def undo_cmd(index: int, assume_yes: bool, group_id: str | None = None) -> int:
    resolved = _resolve_target(group_id)
    if not resolved:
        return 1
    resolved_group_id, _client = resolved
    if index < 1:
        print("Count must be a positive integer.", file=sys.stderr)
        return 1

    activities = get_activities(resolved_group_id, index)
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

    delete_expense(resolved_group_id, expense_id)
    print("Undid:")
    print(f"- {activity_label(str(activity['activityType']))}: {title}")
    return 0


def list_reimbursements(group_id: str | None = None) -> int:
    resolved = _resolve_target(group_id)
    if not resolved:
        return 1
    resolved_group_id, client = resolved

    id_name, _, currency = _participant_maps(client)
    reimbursements = get_balances(resolved_group_id)["reimbursements"]
    if not reimbursements:
        print("No suggested reimbursements.")
        return 0

    for index, reimbursement in enumerate(reimbursements, start=1):
        from_name = id_name.get(reimbursement["from"], reimbursement["from"])
        to_name = id_name.get(reimbursement["to"], reimbursement["to"])
        amount = reimbursement["amount"] / 100
        print(f"{index}. {from_name} -> {to_name} ({currency}{amount:.2f})")

    return 0


def mark_reimbursement_paid(index: int, assume_yes: bool, group_id: str | None = None) -> int:
    resolved = _resolve_target(group_id)
    if not resolved:
        return 1
    resolved_group_id, client = resolved

    id_name, _, currency = _participant_maps(client)
    reimbursements = get_balances(resolved_group_id)["reimbursements"]
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

    settle_reimbursement(resolved_group_id, from_id, to_id, amount)
    print(f"Marked as paid: {from_name} -> {to_name} ({currency}{amount_display:.2f})")
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
