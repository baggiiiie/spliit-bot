"""Resolve the target Spliit group for local CLI commands."""

from __future__ import annotations

import sys


def resolve_cli_target(group_id: str | None) -> str | None:
    if not group_id:
        print("Missing required --spliit-group.", file=sys.stderr)
        return None
    return group_id
