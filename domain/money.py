from __future__ import annotations


def format_money(amount_cents: int, currency: str) -> str:
    return f"{currency}{amount_cents / 100:.2f}"
