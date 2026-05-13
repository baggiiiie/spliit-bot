"""Expense text parsing (regex and LLM-based)."""

from __future__ import annotations

import logging
import re
from functools import cache
from pathlib import Path

from groq import APIError, APITimeoutError, AsyncGroq, RateLimitError
from instructor import from_groq
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from config import GROQ_API_BASE_URL, GROQ_API_KEY, GROQ_MODEL
from domain.expense import LLMParsedExpense, ParseFailure

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.txt"

_FORMAT_HINT = "Please use the format:\n`/add $title, $amount, with p1, p2, and p3`"
_REJECTED_MSG = f"Your request has been rejected. {_FORMAT_HINT}"
_NOT_UNDERSTOOD_MSG = f"Could not understand the expense. {_FORMAT_HINT}"
_LLM_ERROR_MSG = "Error with LLM. Please try again later."
_MAX_LLM_ATTEMPTS = 3
_PAYER_SIGNAL_RE = re.compile(
    r"\b(paid|paying|covered|covering|bought|buying|spent|spending|fronted|fronting)\b",
    re.IGNORECASE,
)


class LLMExpenseResponse(BaseModel):
    """Validated JSON shape requested from the LLM."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    amount: float | None = None
    payer: str | None = None
    participants: list[str] | None = None
    error: str | None = None

    @field_validator("amount", mode="after")
    @classmethod
    def _non_positive_amount_to_none(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            return None
        return value

    @field_validator("title", "payer", "error", mode="before")
    @classmethod
    def _blank_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("participants", mode="before")
    @classmethod
    def _empty_participants_to_none(cls, value: object) -> object:
        if value == []:
            return None
        return value


@cache
def prompt_template() -> str:
    return _PROMPT_PATH.read_text()


def _has_explicit_payer_signal(text: str) -> bool:
    return bool(_PAYER_SIGNAL_RE.search(text))


def _raw_completion_text(completion: object) -> str | None:
    choices = getattr(completion, "choices", None)
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    return content.strip() if isinstance(content, str) else None


def parse_add_command(
    text: str, known_participants: list[str] | None = None
) -> LLMParsedExpense | None:
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
        return LLMParsedExpense(title=title, amount=amount)

    names_text = parts[2].lower()
    matched = [name for name in known_participants if name.lower() in names_text]
    if not matched:
        return LLMParsedExpense(title=title, amount=amount)

    return LLMParsedExpense(title=title, amount=amount, participants=[n.lower() for n in matched])


def _should_try_llm(raw_text: str, participant_names: list[str]) -> bool:
    has_number = bool(re.search(r"\d", raw_text))
    has_participant = any(name.lower() in raw_text.lower() for name in participant_names)
    return has_number or has_participant


async def parse_add_text(
    text: str,
    participant_names: list[str],
) -> LLMParsedExpense | ParseFailure | None:
    expense = parse_add_command(text, participant_names)
    raw_text = re.sub(r"^/add[-_]?bill?\s*", "", text, count=1, flags=re.IGNORECASE).strip()
    if expense:
        return expense
    if not _should_try_llm(raw_text, participant_names):
        return None
    llm_result, _raw_response = await parse_with_llm(raw_text, participant_names)
    return llm_result


async def parse_with_llm(
    text: str, participant_names: list[str]
) -> tuple[LLMParsedExpense | ParseFailure | None, str | None]:
    prompt = prompt_template().format(
        participants=", ".join(participant_names),
        message=text,
    )

    raw_response = None
    try:
        if not GROQ_API_KEY:
            logger.error("GROQ_API_KEY is not set")
            return ParseFailure(user_message=_LLM_ERROR_MSG), None

        client = from_groq(AsyncGroq(api_key=GROQ_API_KEY, base_url=GROQ_API_BASE_URL.rstrip("/")))
        llm_data, completion = await client.chat.completions.create_with_completion(
            response_model=LLMExpenseResponse,
            model=GROQ_MODEL,
            temperature=0,
            max_tokens=120,
            max_retries=_MAX_LLM_ATTEMPTS,
            messages=[
                {
                    "role": "system",
                    "content": "Extract the expense details into the requested schema.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw_response = _raw_completion_text(completion) or llm_data.model_dump_json(
            exclude_none=True
        )

        if llm_data.error:
            return ParseFailure(
                user_message=_NOT_UNDERSTOOD_MSG, raw_response=raw_response
            ), raw_response

        known_lower = {n.lower(): n for n in participant_names}

        matched_payer = (
            known_lower[llm_data.payer.lower()]
            if llm_data.payer and llm_data.payer.lower() in known_lower
            else None
        )
        if matched_payer and not _has_explicit_payer_signal(text):
            matched_payer = None
        matched_payees = (
            [
                known_lower[p.lower()].lower()
                for p in llm_data.participants
                if p.lower() in known_lower
            ]
            if llm_data.participants
            else None
        ) or None

        parsed = LLMParsedExpense(
            title=llm_data.title,
            amount=llm_data.amount,
            payer=matched_payer,
            participants=matched_payees,
        )

        if not parsed.title and not parsed.amount and not parsed.payer and not parsed.participants:
            return ParseFailure(
                user_message=_NOT_UNDERSTOOD_MSG, raw_response=raw_response
            ), raw_response

        return parsed, raw_response
    except ValidationError as e:
        logger.error("LLM response validation failed: %s", e)
        return ParseFailure(user_message=_REJECTED_MSG, raw_response=raw_response), raw_response
    except APITimeoutError:
        logger.error("Groq request timed out")
        return ParseFailure(user_message=_LLM_ERROR_MSG), None
    except RateLimitError as e:
        logger.error("Groq rate limited after retries: %s", e)
        return ParseFailure(user_message=_LLM_ERROR_MSG), None
    except APIError as e:
        logger.error("Groq request failed: %s", e)
        return ParseFailure(user_message=_LLM_ERROR_MSG), None
    except Exception as e:
        logger.error("LLM parse failed: %s", e)
        return ParseFailure(user_message=_LLM_ERROR_MSG, raw_response=raw_response), raw_response
