from __future__ import annotations

import logging

import httpx

from config import GROQ_API_BASE_URL, GROQ_API_KEY, GROQ_WHISPER_MODEL

logger = logging.getLogger(__name__)


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
