# Spliit Telegram Bot

Telegram bot for managing [Spliit](https://spliit.app) expenses.

## Setup

1. Create a bot via [@BotFather](https://t.me/botfather)
2. Get your Spliit group ID from the URL: `https://spliit.app/groups/<GROUP_ID>`
3. Configure:
   ```bash
   cp .env.example .env
   # Edit .env with your TELEGRAM_BOT_TOKEN and GROQ_API_KEY
   ```

   Map each Telegram group chat ID to a Spliit group ID in `groups.json`
   (or set `GROUPS_JSON_PATH`). In Telegram DM, only `ADMIN_TELEGRAM_USER_ID` is allowed;
   use `/switch` there to pick which Spliit group to manage.
4. Install and run:
   ```bash
   uv sync
   uv run python bot.py
   ```

## Deploy with [ONCE](https://github.com/basecamp/once)

ONCE expects the container to listen on **port 80** and respond with HTTP **200** on **`/up`**. The Docker image sets `HEALTH_HTTP_PORT=80` for that. Keep **`BOT_MODE=polling`** (default); webhook on the same port as the health server is not supported.

Put your Telegram/Spliit variables in ONCE’s **Settings → Environment** (or use a local `.env` with `docker run --env-file`, not ONCE). Map `users.json` via **`USERS_JSON_PATH`** if needed; when `/storage` exists (ONCE’s data volume), the default is **`/storage/users.json`** — copy your mapping file there or set the env explicitly.

## Commands

- `/group` - Show participants
- `/add title, amount, with participants` - Add expense

## Local CLI

You can test reimbursement settlement without Telegram:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> group
uv run spliit-cli --spliit-group <GROUP_ID> balance
uv run spliit-cli --spliit-group <GROUP_ID> latest 5
uv run spliit-cli --spliit-group <GROUP_ID> add "Dinner" 50 --paid-by Baggie --with Baggie Neo
uv run spliit-cli --spliit-group <GROUP_ID> add "Taxi" 20.6 --date "2026-04-07T21:21+08:00" --paid-by Baggie --with Baggie Neo
uv run spliit-cli --spliit-group <GROUP_ID> undo
uv run spliit-cli --spliit-group <GROUP_ID> settle list
uv run spliit-cli --spliit-group <GROUP_ID> settle pay 1
uv run spliit-cli --spliit-group <GROUP_ID> settle pay 1 --yes
```

`group`, `balance`, `latest`, `add`, and `undo` mirror the main bot flows for terminal testing.
`settle list` shows the current suggested reimbursements. `settle pay <index>` marks one as paid using
the same Spliit reimbursement API flow as the website. `--spliit-group` is required for the CLI.

## Examples

```
/add dinner, 80, with john, mary, and tom
/add taxi, 25, paid by alice, with alice and bob
```

The bot shows a confirmation before adding expenses.
