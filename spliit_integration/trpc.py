from __future__ import annotations

import json
from typing import Any

import httpx

TRPC_BASE_URL = "https://spliit.app/api/trpc"
TRPC_BATCH_PARAMS = {"batch": "1"}
TRPC_TIMEOUT = 30


def trpc_get(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.get(
        f"{TRPC_BASE_URL}/{path}",
        params={**TRPC_BATCH_PARAMS, "input": json.dumps({"0": {"json": payload}})},
        timeout=TRPC_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return data[0]["result"]["data"]["json"]


def trpc_post(path: str, payload: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
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
