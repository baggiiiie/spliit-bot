#!/bin/bash
set -euo pipefail

run_check() {
  local name=$1
  shift
  local log
  log=$(mktemp)
  if ! "$@" >"$log" 2>&1; then
    echo "[${name}]" >&2
    tail -80 "$log" >&2
    rm -f "$log"
    exit 1
  fi
  rm -f "$log"
}

run_check format uv run ruff format . --check
run_check lint uv run ruff check .
run_check type uv run ty check
run_check test uv run python -m pytest test_bot.py -m 'not llm' -q
run_check llm uv run python -m pytest test_bot.py -m llm -q
