# Spliit Telegram Bot

Telegram bot for managing shared expenses via [Spliit](https://spliit.app).

## Commands

- **Run bot:** `uv run python bot.py`
- **Run tests:** `uv run pytest test_bot.py -m 'not llm' -v`
- **Run LLM tests only:** `uv run pytest test_bot.py -m llm -v`
- **Run all tests:** `uv run pytest test_bot.py -v`
- **Lint:** `uv run ruff check .`
- **Lint fix:** `uv run ruff check --fix .`
- **Format:** `uv run ruff format .`
- **Type check:** `uv run ty check`
- **Install deps:** `uv sync`

After making changes, always run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest test_bot.py -m 'not llm' -v`

Only run LLM tests (`-m llm`) when `prompt.txt` has been modified.

## Project Structure

```
bot.py          — Entrypoint: builds the Telegram Application, registers handlers, starts polling/webhook
config.py       — All configuration, env vars, constants, shared state, type aliases
handlers.py     — Telegram command/callback handlers (add, group, balance, interactive flow)
helpers.py      — Pure UI helpers: keyboard builders, formatting, mention builder, chat validation
parsing.py      — Expense text parsing: regex-based (parse_add_command) and LLM-based (parse_with_llm)
prompt.txt      — LLM prompt template for natural language expense parsing
users.json      — Mapping of Spliit participant names → Telegram user IDs
test_bot.py     — Tests (unit + @pytest.mark.llm integration tests)
```

## Architecture Rules

- **bot.py** is the entrypoint only. It imports handlers and wires them to the Application. No business logic here.
- **config.py** owns all environment variables, constants, type aliases, and module-level shared state (`pending`, `spliit` client). Other modules import from config, never define their own env var reads.
- **handlers.py** contains all Telegram handler functions and external API calls (e.g., `get_balances`). It imports from `config`, `helpers`, and `parsing`. It should not define UI building logic (that goes in `helpers`).
- **helpers.py** contains pure/utility functions for Telegram UI (keyboards, formatting, mentions, chat validation). No handler logic, no Spliit API calls, no external HTTP requests.
- **parsing.py** contains expense text parsing only. No Telegram imports, no side effects beyond LLM subprocess calls.
- Dependencies flow: `bot.py` → `handlers.py` → `helpers.py` / `parsing.py` → `config.py`. No circular imports.

## Conventions

- Python 3.12, managed with `uv`
- Use `httpx` for HTTP requests (not `requests`)
- Use `from __future__ import annotations` in every module
- Type aliases use the `type` keyword (PEP 695): `type PaidFor = list[tuple[str, int]]`
- No type suppressions (`# type: ignore`, `# ty: ignore`)
- Avoid `Any` except for unstructured external API/JSON responses where the shape is unknown
- No code comments unless the logic is complex
- LLM prompts live in separate `.txt` files, loaded at startup, formatted with `str.format()`
- Tests use `pytest`; LLM integration tests are marked `@pytest.mark.llm`
- Import order enforced by ruff: stdlib → third-party → first-party, alphabetized within groups

## Error Handling

- Handlers catch `Exception` at the top level and reply with the error to the user via `update.message.reply_text(f"Error: {e}")`
- Use `assert` for invariants that should never fail (e.g., `assert spliit`, `assert query.data`), not for input validation
- `parse_with_llm` returns `ParsedExpense | str | None`: a `str` means a user-facing error message, `None` means unparseable
- Never silently swallow exceptions; always `logger.error(...)` before returning None or a fallback

## Testing Patterns

- Tests live in `test_bot.py`, organized as classes per module/function
- Test classes: `TestParseAddCommand`, `TestPreLLMFilter`, `TestParseWithLLM`
- Use `@pytest.mark.parametrize` for data-driven tests
- LLM integration tests are marked `@pytest.mark.llm` and should assert on structure (isinstance, field presence) not exact strings
- No mocking of external services yet; handler tests would need Telegram Update mocks

## Do Not Modify

- `.env` — contains secrets, never touch
- `users.json` — production mapping of participant names to Telegram user IDs, do not overwrite with test data
