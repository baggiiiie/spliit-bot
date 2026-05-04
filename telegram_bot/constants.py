"""Telegram callback prefixes and conversation states."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Callback data prefixes
# ---------------------------------------------------------------------------

CB_CONFIRM = "yes_"
CB_CANCEL = "no_"

CB_DEL_CONFIRM = "delyes_"
CB_DEL_CANCEL = "delno_"

CB_SETTLE = "settle_"
CB_SETTLE_CANCEL = "settleno_"

CB_SELECT_GROUP = "selgrp_"

CB_PAYER = "payer_"

CB_PAYEE = "payee_"
CB_PAYEE_DONE = "payee_done"
CB_PAYEE_ALL = "payee_all"

CB_SPLIT_MODE = "splitmode_"

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

TITLE, AMOUNT, PAYER, PAYEES, SELECT_GROUP, SPLIT_MODE, SPLIT_VALUES = range(7)
