"""Expense text parsing (regex and LLM-based)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass

from config import OPENCODE_CLI, OPENCODE_MODEL, PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass
class ParsedExpense:
    title: str
    amount: float
    participants: list[str] | None = None


def parse_add_command(
    text: str, known_participants: list[str] | None = None
) -> ParsedExpense | None:
    text = re.sub(r"^/add\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None

    parts = [p.strip() for p in text.split(",", 2)]
    if len(parts) < 2:
        return None

    title = parts[0]
    amount_match = re.match(r"(\d+(?:\.\d+)?)", parts[1].strip())
    if not amount_match:
        return None
    amount = float(amount_match.group(1))

    if len(parts) < 3 or not known_participants:
        return ParsedExpense(title=title, amount=amount)

    names_text = parts[2].lower()
    matched = [
        name for name in known_participants if name.lower() in names_text
    ]
    if not matched:
        return ParsedExpense(title=title, amount=amount)

    return ParsedExpense(
        title=title, amount=amount, participants=[n.lower() for n in matched]
    )


def parse_with_llm(
    text: str, participant_names: list[str]
) -> ParsedExpense | str | None:
    prompt = PROMPT_TEMPLATE.format(
        participants=", ".join(participant_names),
        message=text,
    )

    try:
        result = subprocess.run(
            [OPENCODE_CLI, "run", "-m", OPENCODE_MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"opencode CLI failed: {result.stderr}")
            return None
        raw = result.stdout.strip()

        json_match = re.search(r"\{[^}]+\}", raw)
        if not json_match:
            return None
        data = json.loads(json_match.group())

        if "error" in data:
            return (
                "Could not understand the expense. Please use the format:\n"
                "`/add $title, $amount, with p1, p2, and p3`"
            )

        title = data.get("title")
        amount = data.get("amount")
        if not title or not isinstance(amount, (int, float)) or amount <= 0:
            return None

        participants = data.get("participants")
        if isinstance(participants, list) and participants:
            known_lower = {n.lower(): n for n in participant_names}
            matched = [known_lower[p.lower()] for p in participants if p.lower() in known_lower]
            if matched:
                return ParsedExpense(
                    title=title, amount=float(amount), participants=[n.lower() for n in matched]
                )

        return ParsedExpense(title=title, amount=float(amount))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"LLM JSON parse failed: {e}")
        return None
    except Exception as e:
        logger.error(f"LLM parse failed: {e}")
        return None
