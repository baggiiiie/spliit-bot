# Autoresearch: improve LLM expense extraction reliability

## Objective
Increase the success rate of turning natural-language `/add` messages into correct structured expense data for the bot. The target workload is the live Groq-backed `parse_with_llm()` path used when regex parsing fails. Optimizations should improve extraction quality for real user phrasings, especially cases that are complete enough for the bot to proceed directly to confirmation without extra interactive questions.

## Metrics
- **Primary**: `pass_rate` (%, higher is better) — exact-case success rate on the prompt evaluation suite
- **Secondary**: `tool_ready_rate`, `field_rate`, `false_positive_count` — monitor direct-to-confirm quality, partial extraction quality, and mistaken expense detections

## How to Run
`./autoresearch.sh` — validates the prompt loads, runs the live LLM eval suite, and outputs structured `METRIC` lines.

## Files in Scope
- `prompt.txt` — LLM extraction instructions and few-shot examples
- `parsing.py` — extraction request/normalization logic if needed
- `autoresearch_eval.py` — live eval suite for prompt quality
- `test_bot.py` — unit and LLM regression coverage
- `autoresearch.sh` — benchmark driver
- `autoresearch.checks.sh` — correctness checks

## Off Limits
- `.env`
- `users.json`
- `groups.json`
- unrelated bot behavior outside expense parsing

## Constraints
- Keep the bot architecture intact
- No new dependencies
- Preserve JSON-only responses from the model
- Format, lint, typecheck, and tests must pass
- Run LLM tests when `prompt.txt` changes
- Do not overfit by hard-coding eval answers in parsing logic

## What's Been Tried
- Baseline setup created with a live eval harness (`autoresearch_eval.py`) covering complete expenses, partial expenses, and obvious non-expense messages.
- Initial hypothesis: the current prompt is too underspecified for title cleanup, `everyone`/`all of us` expansion, and payer/participant role separation.
- A classification-first prompt plus bounded 429 retries in `parse_with_llm()` reached 100% on the initial 16-case suite and passed all checks.
- To avoid overfitting, the next workload broadens the eval suite with more natural phrasings: `split among`, explicit `everyone` with payer, `only X splitting`, `+` participant separators, a money-related non-expense question, and a tricky single-participant/no-payer case (`add coffee beans 14 for baggie only`) that currently tempts payer hallucination.
