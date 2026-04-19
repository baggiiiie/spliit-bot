"""Expense text parsing (regex and LLM-based)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

import httpx

from config import GROQ_API_BASE_URL, GROQ_API_KEY, GROQ_MODEL, GROQ_WHISPER_MODEL, PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

_FORMAT_HINT = "Please use the format:\n`/add $title, $amount, with p1, p2, and p3`"
_REJECTED_MSG = f"Your request has been rejected. {_FORMAT_HINT}"
_NOT_UNDERSTOOD_MSG = f"Could not understand the expense. {_FORMAT_HINT}"
_LLM_ERROR_MSG = "Error with LLM. Please try again later."
_MAX_LLM_ATTEMPTS = 3
_RATE_LIMIT_DELAY_RE = re.compile(r"try again in ([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)
_PAYER_SIGNAL_RE = re.compile(
    r"\b(paid|paying|covered|covering|bought|buying|spent|spending|fronted|fronting)\b",
    re.IGNORECASE,
)


@dataclass
class ParsedExpense:
    title: str | None = None
    amount: float | None = None
    payer: str | None = None
    participants: list[str] | None = None


def _has_explicit_payer_signal(text: str) -> bool:
    return bool(_PAYER_SIGNAL_RE.search(text))


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


async def transcribe_voice(
    file_bytes: bytes, filename: str = "voice.ogg", prompt: str | None = None
) -> str | None:
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not set")
        return None
    try:
        data: dict[str, str] = {"model": GROQ_WHISPER_MODEL, "response_format": "json"}
        if prompt:
            data["prompt"] = prompt
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GROQ_API_BASE_URL.rstrip('/')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (filename, file_bytes, "audio/ogg")},
                data=data,
            )
        if resp.status_code >= 400:
            logger.error("Whisper API error: %s %s", resp.status_code, resp.text)
            return None
        text = resp.json().get("text", "").strip()
        return text or None
    except Exception as e:
        logger.error("Whisper transcription failed: %s", e)
        return None


async def parse_with_llm(
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
            return _LLM_ERROR_MSG, None

        async with httpx.AsyncClient(timeout=30) as client:
            resp = None
            for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
                resp = await client.post(
                    f"{GROQ_API_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    json={
                        "model": GROQ_MODEL,
                        "temperature": 0,
                        "max_tokens": 120,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a JSON-only assistant. Always respond with a single "
                                    "JSON object and nothing else."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                if resp.status_code != 429:
                    break
                raw_response = resp.text
                if attempt >= _MAX_LLM_ATTEMPTS:
                    break
                delay_match = _RATE_LIMIT_DELAY_RE.search(resp.text)
                delay_seconds = float(delay_match.group(1)) if delay_match else 1.0
                delay_seconds = min(max(delay_seconds, 0.5), 5.0)
                logger.warning(
                    "Groq rate limited on attempt %s/%s; retrying in %.2fs",
                    attempt,
                    _MAX_LLM_ATTEMPTS,
                    delay_seconds,
                )
                await asyncio.sleep(delay_seconds)

        assert resp is not None
        if resp.status_code >= 400:
            logger.error(f"Groq API error: {resp.status_code} {resp.text}")
            return _LLM_ERROR_MSG, resp.text

        payload = resp.json()
        raw_response = payload.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        json_match = re.search(r"\{[^}]+\}", raw_response)
        if not json_match:
            return _REJECTED_MSG, raw_response
        data = json.loads(json_match.group())

        if "error" in data:
            return _NOT_UNDERSTOOD_MSG, raw_response

        known_lower = {n.lower(): n for n in participant_names}

        amount = data.get("amount")
        payer = data.get("payer")
        participants = data.get("participants")

        matched_payer = (
            known_lower[payer.lower()]
            if isinstance(payer, str) and payer.lower() in known_lower
            else None
        )
        if matched_payer and not _has_explicit_payer_signal(text):
            matched_payer = None
        matched_payees = (
            [known_lower[p.lower()].lower() for p in participants if p.lower() in known_lower]
            if isinstance(participants, list) and participants
            else None
        ) or None  # convert empty list to None

        parsed = ParsedExpense(
            title=data.get("title") or None,
            amount=float(amount) if isinstance(amount, (int, float)) and amount > 0 else None,
            payer=matched_payer,
            participants=matched_payees,
        )

        if not parsed.title and not parsed.amount and not parsed.payer and not parsed.participants:
            return _NOT_UNDERSTOOD_MSG, raw_response

        return parsed, raw_response
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"LLM JSON parse failed: {e}")
        return _REJECTED_MSG, raw_response
    except httpx.TimeoutException:
        logger.error("Groq request timed out")
        return _LLM_ERROR_MSG, None
    except httpx.HTTPError as e:
        logger.error(f"Groq request failed: {e}")
        return _LLM_ERROR_MSG, None
    except Exception as e:
        logger.error(f"LLM parse failed: {e}")
        return _LLM_ERROR_MSG, raw_response
