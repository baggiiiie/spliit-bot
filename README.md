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

## Examples

```
/add dinner, 80, with john, mary, and tom
/add taxi, 25, paid by alice, with alice and bob
```

The bot shows a confirmation before adding expenses.
