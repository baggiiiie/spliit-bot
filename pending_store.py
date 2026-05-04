"""In-memory pending action stores for Telegram callbacks."""

from __future__ import annotations

from constants import PendingDelete, PendingExpense, PendingSettlement

pending: dict[str, PendingExpense] = {}
pending_deletes: dict[str, PendingDelete] = {}
pending_settlements: dict[str, PendingSettlement] = {}
