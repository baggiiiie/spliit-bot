# Spliit Telegram Bot

Telegram bot and local CLI for managing a Spliit group.

## Core Commands

- Run bot: `uv run python bot.py`
- Run CLI: `uv run spliit-cli`
- Format: `uv run ruff format .`
- Lint: `uv run ruff check .`
- Type check: `uv run ty check`
- Tests: `uv run python -m pytest test_bot.py -m 'not llm' -v`
- LLM tests only: `uv run python -m pytest test_bot.py -m llm -v`

After changes, run:
`uv run ruff format . && uv run ruff check . && uv run ty check && uv run python -m pytest test_bot.py -m 'not llm' -v`

Run `-m llm` tests only when `prompt.txt` changes.

## Files

- `bot.py`: entrypoint only; registers Telegram handlers and starts polling/webhook
- `config.py`: env vars, constants, shared state, type aliases
- `handlers.py`: Telegram command/callback handlers
- `helpers.py`: pure Telegram UI helpers and chat validation
- `health_http.py`: GET `/up` health server (e.g. ONCE)
- `parsing.py`: expense parsing only
- `services.py`: Spliit HTTP calls
- `cli.py`: local CLI that mirrors bot flows
- `prompt.txt`: LLM prompt template
- `test_bot.py`: unit tests and LLM integration tests

## Architecture Rules

- Keep `bot.py` thin. No business logic there.
- Read environment variables only in `config.py`.
- Keep Telegram-specific flow in `handlers.py`.
- Keep `helpers.py` pure: no handler logic, no HTTP calls.
- Keep `parsing.py` focused on parsing. No Telegram imports.
- Put Spliit API access in `services.py`.
- Avoid circular imports. Preferred flow: `bot.py` -> `handlers.py` -> `helpers.py` / `parsing.py` / `services.py` -> `config.py`.

## Conventions

- Python 3.12 with `uv`
- Always use `from __future__ import annotations`
- Use `httpx`, not `requests`
- Use PEP 695 `type` aliases
- No `# type: ignore` or `# ty: ignore`
- Avoid `Any` except for unknown external JSON
- Keep comments minimal
- Ruff import order: stdlib, third-party, first-party

## Error Handling

- Handler top-level failures should log and reply with `Error: {e}`
- Use `assert` for invariants, not user input validation
- `parse_with_llm` returns `ParsedExpense | str | None`
- Do not swallow exceptions silently

## Testing Notes

- Keep tests in `test_bot.py`
- Prefer `@pytest.mark.parametrize` for matrix cases
- Mark real-LLM tests with `@pytest.mark.llm`
- Assert structure for LLM tests, not exact wording

## Safety

- Never modify `.env`
- Never overwrite `users.json` with test data
