"""Split allocation rules for Spliit expenses."""

from __future__ import annotations

from enum import StrEnum

type PaidFor = list[tuple[str, int]]


class SplitMode(StrEnum):
    EVENLY = "EVENLY"
    BY_SHARES = "BY_SHARES"
    BY_PERCENTAGE = "BY_PERCENTAGE"
    BY_AMOUNT = "BY_AMOUNT"


def parse_split_values(
    text: str,
    payee_ids: list[str],
    payee_names: list[str],
    split_mode: SplitMode,
    amount_cents: int,
) -> tuple[PaidFor, str | None]:
    """Parse positional split values entered by the user.

    Returns ``(paid_for, None)`` on success or ``([], error_message)`` on failure.
    Input is whitespace- or comma-separated numbers, one per payee in order.
    Share semantics match ``split_mode``.
    """
    raw = [tok for tok in text.replace(",", " ").split() if tok]
    if len(raw) != len(payee_ids):
        return [], (
            f"Expected {len(payee_ids)} values (one per payee), got {len(raw)}.\n"
            f"Order: {', '.join(payee_names)}"
        )

    if split_mode is SplitMode.BY_SHARES:
        shares: list[int] = []
        for tok in raw:
            try:
                value = int(tok)
            except ValueError:
                return [], f"'{tok}' is not a whole number. Use integer shares like: 2 1 1"
            if value <= 0:
                return [], "Shares must be positive integers."
            shares.append(value)
        return list(zip(payee_ids, shares, strict=True)), None

    if split_mode is SplitMode.BY_PERCENTAGE:
        bps_list: list[int] = []
        for tok in raw:
            try:
                pct = float(tok)
            except ValueError:
                return [], f"'{tok}' is not a number. Use percentages like: 50 30 20"
            if pct < 0:
                return [], "Percentages must be non-negative."
            bps_list.append(round(pct * 100))
        if sum(bps_list) != 10000:
            return [], f"Percentages must sum to 100 (got {sum(bps_list) / 100:g})."
        return list(zip(payee_ids, bps_list, strict=True)), None

    if split_mode is SplitMode.BY_AMOUNT:
        cents_list: list[int] = []
        for tok in raw:
            try:
                amt = float(tok)
            except ValueError:
                return [], f"'{tok}' is not a number. Use amounts like: 20 15 5"
            if amt < 0:
                return [], "Amounts must be non-negative."
            cents_list.append(round(amt * 100))
        total = sum(cents_list)
        if total != amount_cents:
            return [], (f"Amounts must sum to {amount_cents / 100:.2f} (got {total / 100:.2f}).")
        return list(zip(payee_ids, cents_list, strict=True)), None

    return [(pid, 1) for pid in payee_ids], None
