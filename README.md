# Spliit Telegram Bot

Telegram bot for managing [Spliit](https://spliit.app) expenses.

## Setup

1. Create a bot via [@BotFather](https://t.me/botfather)
2. Get your Spliit group ID from the URL: `https://spliit.app/groups/<GROUP_ID>`
3. Configure:
   ```bash
   cp .env.example .env
   # Edit .env with your TELEGRAM_BOT_TOKEN, SPLIIT_GROUP_ID, and GROQ_API_KEY
   ```
4. Install and run:
   ```bash
   pip install -r requirements.txt
   python bot.py
   ```

## Commands

- `/group` - Show participants
- `/add title, amount, with participants` - Add expense

## Local CLI

You can test reimbursement settlement without Telegram:

```bash
uv run spliit-cli group
uv run spliit-cli balance
uv run spliit-cli latest --limit 5
uv run spliit-cli add "Dinner" 50 --paid-by Baggie --with Baggie Neo
uv run spliit-cli undo
uv run spliit-cli settle list
uv run spliit-cli settle pay 1
uv run spliit-cli settle pay 1 --yes
```

`group`, `balance`, `latest`, `add`, and `undo` mirror the main bot flows for terminal testing.
`settle list` shows the current suggested reimbursements. `settle pay <index>` marks one as paid using
the same Spliit reimbursement API flow as the website.

## Examples

```
/add dinner, 80, with john, mary, and tom
/add taxi, 25, paid by alice, with alice and bob
```

The bot shows a confirmation before adding expenses.
