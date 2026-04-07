from __future__ import annotations

import json
from typing import Any

import httpx
from spliit.utils import get_current_timestamp


def get_balances(group_id: str) -> dict[str, Any]:
    params_input = {"0": {"json": {"groupId": group_id}}}
    params = {"batch": "1", "input": json.dumps(params_input)}
    response = httpx.get("https://spliit.app/api/trpc/groups.balances.list", params=params)
    return response.json()[0]["result"]["data"]["json"]


def get_expenses(group_id: str) -> list[dict[str, Any]]:
    params_input = {"0": {"json": {"groupId": group_id}}}
    params = {"batch": "1", "input": json.dumps(params_input)}
    response = httpx.get("https://spliit.app/api/trpc/groups.expenses.list", params=params)
    data = response.json()
    return data[0]["result"]["data"]["json"]["expenses"]


def get_activities(group_id: str, limit: int, cursor: int = 0) -> list[dict[str, Any]]:
    params_input = {"0": {"json": {"groupId": group_id, "cursor": cursor, "limit": limit}}}
    params = {"batch": "1", "input": json.dumps(params_input)}
    response = httpx.get("https://spliit.app/api/trpc/groups.activities.list", params=params)
    data = response.json()
    return data[0]["result"]["data"]["json"]["activities"]


def delete_expense(group_id: str, expense_id: str) -> None:
    params = {"batch": "1"}
    json_data = {
        "0": {
            "json": {
                "groupId": group_id,
                "expenseId": expense_id,
            },
        },
    }
    response = httpx.post(
        "https://spliit.app/api/trpc/groups.expenses.delete",
        params=params,
        json=json_data,
    )
    response.raise_for_status()


def create_expense(
    group_id: str,
    title: str,
    paid_by: str,
    paid_for: list[tuple[str, int]],
    amount: int,
    expense_date: str | None = None,
    category: int = 0,
    is_reimbursement: bool = False,
) -> None:
    params = {"batch": "1"}
    json_data = {
        "0": {
            "json": {
                "groupId": group_id,
                "expenseFormValues": {
                    "expenseDate": expense_date or get_current_timestamp(),
                    "title": title,
                    "category": category,
                    "amount": amount,
                    "paidBy": paid_by,
                    "paidFor": [
                        {"participant": participant_id, "shares": shares}
                        for participant_id, shares in paid_for
                    ],
                    "splitMode": "EVENLY",
                    "saveDefaultSplittingOptions": False,
                    "isReimbursement": is_reimbursement,
                    "documents": [],
                    "notes": "",
                },
                "participantId": "None",
            },
            "meta": {
                "values": {
                    "expenseFormValues.expenseDate": ["Date"],
                }
            },
        }
    }
    response = httpx.post(
        "https://spliit.app/api/trpc/groups.expenses.create",
        params=params,
        json=json_data,
    )
    response.raise_for_status()


def settle_reimbursement(group_id: str, from_id: str, to_id: str, amount: int) -> None:
    create_expense(
        group_id=group_id,
        title="Reimbursement",
        paid_by=from_id,
        paid_for=[(to_id, 1)],
        amount=amount,
        category=1,
        is_reimbursement=True,
    )
