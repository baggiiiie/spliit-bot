# Spliit Telegram Bot

A Telegram bot for managing [Spliit](https://spliit.app) expenses directly from Telegram.

## Features

- Add expenses via natural language commands
- Confirmation prompt before creating expenses
- View group participants
- Check current balances
- Split expenses evenly among participants

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token you receive

### 2. Get Your Spliit Group ID

1. Open your Spliit group in a browser
2. The URL will look like: `https://spliit.app/groups/abc123xyz`
3. Copy the group ID (the part after `/groups/`)

### 3. Configure the Bot

```bash
cd spliit-telegram-bot
cp .env.example .env
```

Edit `.env` with your values:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
SPLIIT_BASE_URL=https://spliit.app
SPLIIT_GROUP_ID=your_group_id_here
ALLOWED_USER_IDS=  # Optional: comma-separated Telegram user IDs
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the Bot

```bash
python bot.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message and help |
| `/help` | Show available commands |
| `/group` | Show current group info and participants |
| `/balance` | Show current balances |
| `/add` | Add a new expense |

## Adding Expenses

Use the `/add` command with the following format:

```
/add <title>, <amount> <currency>, with <participants>
```

### Examples

**Basic expense:**
```
/add hotpot dinner, 80 SGD, with john, ricky, and tommy
```

**Specify who paid:**
```
/add groceries, 50 USD, paid by alice, with alice and bob
```

**Multiple participants:**
```
/add taxi, 25 EUR, with john, mary, and peter
```

### How it Works

1. Send the `/add` command with your expense details
2. The bot will show a confirmation message with:
   - Expense title
   - Total amount
   - Who paid
   - Who it's split between
   - Amount each person pays
3. Click **Confirm** to create the expense in Spliit
4. Click **Cancel** to abort

### Notes

- If "paid by" is not specified, the first participant is assumed to be the payer
- Participant names are matched against your Spliit group members (case-insensitive)
- Expenses are split evenly by default

## Self-Hosted Spliit

If you're running your own Spliit instance, update `SPLIIT_BASE_URL` in your `.env`:

```
SPLIIT_BASE_URL=https://your-spliit-instance.com
```

## Security

- Set `ALLOWED_USER_IDS` to restrict bot access to specific Telegram users
- Never commit your `.env` file to version control
- Keep your bot token secret

## License

MIT
