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
- `config.py`: env vars, shared state (pending dicts, Spliit client cache)
- `constants.py`: callback prefixes, conversation states, pending-state dataclasses, `format_money`
- `handlers/`: Telegram command/callback handlers (package)
  - `__init__.py`: re-exports all public handlers
  - `common.py`: shared handler utilities (`resolve_group`, `build_mention`, `_require_group`, etc.)
  - `commands.py`: simple command handlers (`start`, `group_cmd`, `balance_cmd`, `latest_cmd`, `settle_cmd`, `undo_cmd`, `switch_cmd`)
  - `add_flow.py`: `/add` ConversationHandler flow (`add_cmd`, `interactive_*`, `cancel_interactive`)
  - `callbacks.py`: inline callback-query dispatcher (`button`)
- `helpers.py`: pure Telegram UI helpers and chat validation
- `health_http.py`: GET `/up` health server (e.g. ONCE)
- `parsing.py`: expense parsing only (async LLM calls)
- `services.py`: Spliit HTTP calls
- `domain.py`: interface-agnostic Spliit helpers shared by bot and CLI
- `cli.py`: local CLI that mirrors bot flows
- `prompt.txt`: LLM prompt template
- `test_bot.py`: unit tests and LLM integration tests

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
- Avoid circular imports. Preferred flow: `bot.py` -> `handlers/` -> `helpers.py` / `parsing.py` / `services.py` / `domain.py` -> `config.py` / `constants.py`.

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
