"""Expense date normalization for Spliit writes."""

from __future__ import annotations

from datetime import UTC, datetime

DATE_HELP = (
    "Invalid --date. Use ISO 8601, e.g. 2026-04-07, 2026-04-07T21:21, or 2026-04-07T21:21+08:00."
)


def normalize_expense_date(value: str) -> str:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(DATE_HELP) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
