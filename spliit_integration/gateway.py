from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from spliit import Spliit
from spliit.utils import get_current_timestamp

from domain.activity import Activity
from domain.balance import Balance, BalanceReport, Reimbursement
from domain.group import Group
from domain.split import PaidFor, SplitMode
from spliit_integration.trpc import trpc_get, trpc_post


@dataclass(frozen=True, slots=True)
class NewExpense:
    title: str
    paid_by: str
    paid_for: PaidFor
    amount_cents: int
    expense_date: str | None = None
    category: int = 0
    is_reimbursement: bool = False
    split_mode: SplitMode = SplitMode.EVENLY


@dataclass(frozen=True, slots=True)
class Settlement:
    from_id: str
    to_id: str
    amount_cents: int


class SpliitGateway:
    def __init__(self) -> None:
        self._clients: dict[str, Spliit] = {}

    def client(self, group_id: str) -> Spliit:
        if group_id not in self._clients:
            self._clients[group_id] = Spliit(group_id=group_id)
        return self._clients[group_id]

    def group(self, group_id: str) -> Group:
        return Group.from_spliit_dict(self.client(group_id).get_group())

    def balances(self, group_id: str) -> BalanceReport:
        data = trpc_get("groups.balances.list", {"groupId": group_id})
        balances = [
            Balance(participant_id=str(pid), total_cents=int(values["total"]))
            for pid, values in data["balances"].items()
        ]
        reimbursements = [
            Reimbursement(
                from_id=str(item["from"]),
                to_id=str(item["to"]),
                amount_cents=int(item["amount"]),
            )
            for item in data["reimbursements"]
        ]
        return BalanceReport(balances=balances, reimbursements=reimbursements)

    def activities(self, group_id: str, limit: int, cursor: int = 0) -> list[Activity]:
        data = trpc_get(
            "groups.activities.list",
            {"groupId": group_id, "cursor": cursor, "limit": limit},
        )
        return [self._activity_from_spliit_dict(activity) for activity in data["activities"]]

    def _activity_from_spliit_dict(self, activity: object) -> Activity:
        activity_data = cast(Mapping[str, object], activity)
        if activity_data.get("data"):
            subject = str(activity_data["data"])
        elif isinstance(expense := activity_data.get("expense"), Mapping):
            expense_data = cast(Mapping[str, object], expense)
            subject = str(expense_data.get("title", "Untitled"))
        else:
            subject = "Untitled"
        expense_id = activity_data.get("expenseId")
        return Activity(
            activity_type=str(activity_data["activityType"]),
            subject=subject,
            expense_id=str(expense_id) if expense_id else None,
        )

    def create_expense(self, group_id: str, expense: NewExpense) -> None:
        trpc_post(
            "groups.expenses.create",
            {
                "groupId": group_id,
                "expenseFormValues": {
                    "expenseDate": expense.expense_date or get_current_timestamp(),
                    "title": expense.title,
                    "category": expense.category,
                    "amount": expense.amount_cents,
                    "paidBy": expense.paid_by,
                    "paidFor": [
                        {"participant": participant_id, "shares": shares}
                        for participant_id, shares in expense.paid_for
                    ],
                    "splitMode": expense.split_mode.value,
                    "saveDefaultSplittingOptions": False,
                    "isReimbursement": expense.is_reimbursement,
                    "documents": [],
                    "notes": "",
                },
                "participantId": "None",
            },
            meta={"values": {"expenseFormValues.expenseDate": ["Date"]}},
        )

    def delete_expense(self, group_id: str, expense_id: str) -> None:
        trpc_post(
            "groups.expenses.delete",
            {"groupId": group_id, "expenseId": expense_id},
        )

    def settle(self, group_id: str, settlement: Settlement) -> None:
        self.create_expense(
            group_id,
            NewExpense(
                title="Reimbursement",
                paid_by=settlement.from_id,
                paid_for=[(settlement.to_id, 1)],
                amount_cents=settlement.amount_cents,
                category=1,
                is_reimbursement=True,
            ),
        )


gateway = SpliitGateway()
