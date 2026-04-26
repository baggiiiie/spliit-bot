# Spliit Telegram Bot

Telegram bot and local CLI for managing a Spliit group.

## using AGENTS.md

If you encounter something surprising or confusing in this project, add it to this file.

## Core Commands

- Run bot: `uv run python bot.py`
- Run CLI: `uv run spliit-cli`
- Tests: `uv run python -m pytest test_bot.py -m 'not llm' -v`
- LLM tests only: `uv run python -m pytest test_bot.py -m llm -v`

After changes, run:
`uv run ruff format . && uv run ruff check . && uv run ty check && uv run python -m pytest test_bot.py -m 'not llm' -v`

Run `-m llm` tests only when `prompt.txt` changes.

## Architecture Rules

- Keep `bot.py` thin. No business logic there.
- Read environment variables only in `config.py`.
- Keep Telegram-specific flow in `handlers/`.
- Keep `helpers.py` pure: no handler logic, no HTTP calls.
- Keep `parsing.py` focused on parsing. No Telegram imports.
- Put Spliit API access in `services.py`.
- Use callback prefix constants from `constants.py`, never magic strings.
- Use pending-state dataclasses (`PendingExpense`, `PendingDelete`, `PendingSettlement`), never raw tuples.
- Use `format_money()` for cents→display formatting, never inline `/ 100`.

## Conventions

- Always use `from __future__ import annotations`
- Use `httpx`, not `requests`
- Use PEP 695 `type` aliases
- No `# type: ignore` or `# ty: ignore`
- Avoid `Any` except for unknown external JSON

## Error Handling

- Handler top-level failures should log and reply with `Error: {e}`
- Use `assert` for invariants, not user input validation
- `parse_with_llm` returns `ParsedExpense | str | None`
- Do not swallow exceptions silently

## Testing Notes

- Keep tests in `test_bot.py`
- Prefer `@pytest.mark.parametrize` for matrix cases
- Mark real-LLM tests with `@pytest.mark.llm`

## Safety

- Never modify `.env`
- Never overwrite `users.json` with test data
