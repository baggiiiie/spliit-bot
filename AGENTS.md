# Spliit Telegram Bot

Telegram bot for managing shared expenses via [Spliit](https://spliit.app).

## Commands

- **Run bot:** `uv run python bot.py`
- **Run tests:** `uv run pytest test_bot.py -v`
- **Run tests (skip LLM):** `uv run pytest test_bot.py -m 'not llm' -v`
- **Run LLM tests only:** `uv run pytest test_bot.py -m llm -v`
- **Install deps:** `uv sync`

## Project Structure

- `bot.py` — Main bot logic (handlers, parsing, Spliit API interaction)
- `prompt.txt` — LLM prompt template for natural language expense parsing
- `users.json` — Mapping of Spliit participant names to Telegram user IDs
- `test_bot.py` — Tests (unit tests + `@pytest.mark.llm` integration tests)
- `.env` — Environment variables (not committed)

## Conventions

- Python 3.12, managed with `uv`
- No type suppressions (`# type: ignore`, `Any` casts)
- No code comments unless the logic is complex
- LLM prompts live in separate `.txt` files, loaded at startup, formatted with `str.format()`
- Tests use `pytest`; LLM integration tests are marked `@pytest.mark.llm`
- Only run LLM tests (`-m llm`) when `prompt.txt` has been modified; otherwise use `-m 'not llm'`
