"""Resolve the target Spliit group for local CLI commands."""

from __future__ import annotations

import sys

from spliit import Spliit

from config import get_spliit


def resolve_cli_target(group_id: str | None) -> tuple[str, Spliit] | None:
    if not group_id:
        print("Missing required --spliit-group.", file=sys.stderr)
        return None
    return group_id, get_spliit(group_id)
