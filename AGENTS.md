# Spliit Telegram Bot

Telegram bot and local CLI for managing a Spliit group.

## using AGENTS.md

If you encounter something surprising or confusing in this project, add it to this file.

## Core Commands

- Run bot: `uv run python app.py` (or `uv run spliit-bot`)
- Run CLI: `uv run spliit-cli`
- Tests: `uv run python -m pytest test_bot.py -m 'not llm' -v`
- LLM tests only: `uv run python -m pytest test_bot.py -m llm -v`

After changes, run:
`uv run ruff format . && uv run ruff check . && uv run ty check && uv run python -m pytest test_bot.py -m 'not llm' -v`

Run `-m llm` tests only when `prompt.txt` changes.

## Architecture Rules

- Keep `app.py` thin. No business logic there; it only wires `telegram_bot/routing.build_handlers`.
- Read environment variables only in `config.py`. No side effects beyond reading env.
- Load `users.json` / `groups.json` via `domain/registry.py`, not in `config.py`.
- Keep Telegram-specific flow in `telegram_bot/`.
- Keep Telegram identity/access helpers in `telegram_bot/access.py`: no handler logic, no HTTP calls.
- Keep Telegram rendering and callback reply helpers in `telegram_bot/ui.py`.
- Keep LLM parsing in `llm/parser.py` and voice transcription in `llm/voice.py`. No Telegram imports. The prompt template is read lazily from `prompt.txt` inside `llm/parser.py`.
- Put Spliit API access in `spliit_integration/` (`gateway.py`, `trpc.py`). Only `trpc.py` may use `dict[str, Any]`; the gateway returns typed `domain/` value objects.
- Use callback prefix and conversation state constants from `telegram_bot/constants.py`, never magic strings.
- Use pending-state dataclasses from `telegram_bot/session.py` (`PendingExpense`, `PendingDelete`, `PendingSettlement`), never raw tuples. Access `context.user_data` only through `Session`.
- Use `SplitMode` / `PaidFor` from `domain/split.py`.
- Use `format_money()` from `domain/money.py` for cents→display formatting, never inline `/ 100`.
- Keep CLI entry in `cli/__main__.py` and CLI-only formatting in `cli/format.py`.
- Keep infra concerns (logging, health HTTP) in `infra/`.

## Conventions

- Always use `from __future__ import annotations`
- Use `httpx`, not `requests`
- Use PEP 695 `type` aliases
- No `# type: ignore` or `# ty: ignore`
- Avoid `Any` except for unknown external JSON

## Error Handling

- Handler top-level failures should log and reply with `Error: {e}`
- Use `assert` for invariants, not user input validation
- `parse_with_llm` returns `LLMParsedExpense | ParseFailure | None`
- Do not swallow exceptions silently

## Testing Notes

- Keep tests in `test_bot.py`
- Prefer `@pytest.mark.parametrize` for matrix cases
- Mark real-LLM tests with `@pytest.mark.llm`

## Safety

- Never modify `.env`
- Never overwrite `users.json` with test data
