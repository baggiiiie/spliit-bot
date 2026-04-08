from __future__ import annotations

import json
from typing import Any

import httpx
from spliit.utils import get_current_timestamp

TRPC_BASE_URL = "https://spliit.app/api/trpc"
TRPC_BATCH_PARAMS = {"batch": "1"}
TRPC_TIMEOUT = 30


def _trpc_get(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.get(
        f"{TRPC_BASE_URL}/{path}",
        params={
            **TRPC_BATCH_PARAMS,
            "input": json.dumps({"0": {"json": payload}}),
        },
        timeout=TRPC_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return data[0]["result"]["data"]["json"]


def _trpc_post(path: str, payload: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
    request_body: dict[str, Any] = {"0": {"json": payload}}
    if meta:
        request_body["0"]["meta"] = meta

    response = httpx.post(
        f"{TRPC_BASE_URL}/{path}",
        params=TRPC_BATCH_PARAMS,
        json=request_body,
        timeout=TRPC_TIMEOUT,
    )
    response.raise_for_status()


def get_balances(group_id: str) -> dict[str, Any]:
    return _trpc_get("groups.balances.list", {"groupId": group_id})


def get_expenses(group_id: str) -> list[dict[str, Any]]:
    data = _trpc_get("groups.expenses.list", {"groupId": group_id})
    return data["expenses"]


def get_activities(group_id: str, limit: int, cursor: int = 0) -> list[dict[str, Any]]:
    data = _trpc_get(
        "groups.activities.list",
        {"groupId": group_id, "cursor": cursor, "limit": limit},
    )
    return data["activities"]


def delete_expense(group_id: str, expense_id: str) -> None:
    _trpc_post(
        "groups.expenses.delete",
        {
            "groupId": group_id,
            "expenseId": expense_id,
        },
    )


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
    _trpc_post(
        "groups.expenses.create",
        {
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
        meta={
            "values": {
                "expenseFormValues.expenseDate": ["Date"],
            }
        },
    )


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
