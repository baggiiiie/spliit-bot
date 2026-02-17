"""Expense text parsing (regex and LLM-based)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from config import GROQ_API_BASE_URL, GROQ_API_KEY, GROQ_MODEL, PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass
class ParsedExpense:
    title: str | None = None
    amount: float | None = None
    payer: str | None = None
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
    matched = [name for name in known_participants if name.lower() in names_text]
    if not matched:
        return ParsedExpense(title=title, amount=amount)

    return ParsedExpense(title=title, amount=amount, participants=[n.lower() for n in matched])


def parse_with_llm(
    text: str, participant_names: list[str]
) -> tuple[ParsedExpense | str | None, str | None]:
    prompt = PROMPT_TEMPLATE.format(
        participants=", ".join(participant_names),
        message=text,
    )

    raw_response = None
    try:
        if not GROQ_API_KEY:
            logger.error("GROQ_API_KEY is not set")
            return "Error with LLM. Please try again later.", None

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{GROQ_API_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": GROQ_MODEL,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": "You are a JSON-only assistant. Always respond with a single JSON object and nothing else."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )

        if resp.status_code >= 400:
            logger.error(f"Groq API error: {resp.status_code} {resp.text}")
            return "Error with LLM. Please try again later.", resp.text

        payload = resp.json()
        raw_response = payload.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        json_match = re.search(r"\{[^}]+\}", raw_response)
        if not json_match:
            return (
                "Your request has been rejected. Please use the format:\n"
                "`/add $title, $amount, with p1, p2, and p3`",
                raw_response,
            )
        data = json.loads(json_match.group())

        if "error" in data:
            return (
                "Could not understand the expense. Please use the format:\n"
                "`/add $title, $amount, with p1, p2, and p3`",
                raw_response,
            )

        title = data.get("title")
        amount = data.get("amount")
        payer = data.get("payer")
        participants = data.get("participants")

        parsed = ParsedExpense()
        if title:
            parsed.title = title
        if isinstance(amount, (int, float)) and amount > 0:
            parsed.amount = float(amount)

        known_lower = {n.lower(): n for n in participant_names}

        if payer and isinstance(payer, str):
            if payer.lower() in known_lower:
                parsed.payer = known_lower[payer.lower()]

        if isinstance(participants, list) and participants:
            matched = [known_lower[p.lower()] for p in participants if p.lower() in known_lower]
            if matched:
                parsed.participants = [n.lower() for n in matched]

        if not parsed.title and not parsed.amount and not parsed.payer and not parsed.participants:
            return (
                "Could not understand the expense. Please use the format:\n"
                "`/add $title, $amount, with p1, p2, and p3`",
                raw_response,
            )

        return parsed, raw_response
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"LLM JSON parse failed: {e}")
        return (
            "Your request has been rejected. Please use the format:\n"
            "`/add $title, $amount, with p1, p2, and p3`",
            raw_response,
        )
    except httpx.TimeoutException:
        logger.error("Groq request timed out")
        return "Error with LLM. Please try again later.", None
    except httpx.HTTPError as e:
        logger.error(f"Groq request failed: {e}")
        return "Error with LLM. Please try again later.", None
    except Exception as e:
        logger.error(f"LLM parse failed: {e}")
        return "Error with LLM. Please try again later.", raw_response
