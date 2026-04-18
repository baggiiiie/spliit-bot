#!/bin/bash
set -euo pipefail

uv run python - <<'PY' >/dev/null
from config import PROMPT_TEMPLATE
assert PROMPT_TEMPLATE.strip()
PY

uv run python autoresearch_eval.py --quiet
