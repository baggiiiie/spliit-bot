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


def settle_reimbursement(group_id: str, from_id: str, to_id: str, amount: int) -> None:
    params = {"batch": "1"}
    json_data = {
        "0": {
            "json": {
                "groupId": group_id,
                "expenseFormValues": {
                    "expenseDate": get_current_timestamp(),
                    "title": "Reimbursement",
                    "category": 1,
                    "amount": amount,
                    "paidBy": from_id,
                    "paidFor": [{"participant": to_id, "shares": 1}],
                    "splitMode": "EVENLY",
                    "saveDefaultSplittingOptions": False,
                    "isReimbursement": True,
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
