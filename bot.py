#!/usr/bin/env python3
"""
Spliit Telegram Bot - Manage Spliit expenses via Telegram.

Commands:
  /start - Show welcome message and help
  /help - Show available commands
  /group - Show current group info and participants
  /add <description>, <amount> <currency>, with <participants> - Add a new expense
  /balance - Show current balances
"""

import os
import re
import logging
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SPLIIT_BASE_URL = os.getenv("SPLIIT_BASE_URL", "https://spliit.app")
SPLIIT_GROUP_ID = os.getenv("SPLIIT_GROUP_ID", "")
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
]


@dataclass
class ParsedExpense:
    """Parsed expense from user input."""

    title: str
    amount: float
    currency: str
    paid_by: str  # Name of person who paid
    participants: list[str]  # Names of participants


@dataclass
class Participant:
    """Spliit group participant."""

    id: str
    name: str


@dataclass
class GroupInfo:
    """Spliit group information."""

    id: str
    name: str
    currency: str
    participants: list[Participant]


# In-memory storage for pending confirmations
pending_confirmations: dict[str, ParsedExpense] = {}


class SpliitClient:
    """Client for interacting with Spliit via tRPC API."""

    def __init__(self, base_url: str, group_id: str):
        self.base_url = base_url.rstrip("/")
        self.group_id = group_id
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_group(self) -> Optional[GroupInfo]:
        """Fetch group information including participants."""
        try:
            # Spliit uses tRPC, so we need to call the appropriate endpoint
            url = f"{self.base_url}/api/trpc/groups.get"
            params = {"input": f'{{"json":{{"groupId":"{self.group_id}"}}}}'}

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            result = data.get("result", {}).get("data", {}).get("json", {})

            if not result:
                return None

            participants = [
                Participant(id=p["id"], name=p["name"])
                for p in result.get("participants", [])
            ]

            return GroupInfo(
                id=result.get("id", self.group_id),
                name=result.get("name", "Unknown"),
                currency=result.get("currency", "USD"),
                participants=participants,
            )
        except Exception as e:
            logger.error(f"Failed to fetch group: {e}")
            return None

    async def create_expense(
        self,
        title: str,
        amount: float,
        paid_by_id: str,
        paid_for: list[dict],
        category: str = "General",
    ) -> Optional[dict]:
        """Create a new expense in Spliit."""
        try:
            url = f"{self.base_url}/api/trpc/groups.expenses.create"

            # Amount should be in cents for Spliit
            amount_cents = int(amount * 100)

            payload = {
                "json": {
                    "groupId": self.group_id,
                    "expenseFormValues": {
                        "title": title,
                        "amount": amount_cents,
                        "category": category,
                        "paidBy": paid_by_id,
                        "paidFor": paid_for,
                        "splitMode": "EVENLY",
                        "isReimbursement": False,
                    },
                }
            }

            response = await self.client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()
            return data.get("result", {}).get("data", {}).get("json")
        except Exception as e:
            logger.error(f"Failed to create expense: {e}")
            return None

    async def get_balances(self) -> Optional[list[dict]]:
        """Get group balances."""
        try:
            url = f"{self.base_url}/api/trpc/groups.balances.list"
            params = {"input": f'{{"json":{{"groupId":"{self.group_id}"}}}}'}

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            return data.get("result", {}).get("data", {}).get("json")
        except Exception as e:
            logger.error(f"Failed to fetch balances: {e}")
            return None

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Initialize Spliit client
spliit_client = SpliitClient(SPLIIT_BASE_URL, SPLIIT_GROUP_ID)


def parse_expense_command(text: str) -> Optional[ParsedExpense]:
    """
    Parse expense command in format:
    /add <title>, <amount> <currency>, with <participants>

    Examples:
    - /add hotpot dinner, 80 SGD, with john, ricky, and tommy
    - /add groceries, 50 USD, with alice and bob
    - /add taxi, 25 EUR, paid by john, with john, mary
    """
    # Remove the /add command prefix
    text = re.sub(r"^/add[-_]?bill?\s*", "", text, flags=re.IGNORECASE).strip()

    if not text:
        return None

    # Pattern to match: title, amount currency, [paid by person,] with participants
    # Example: "hotpot dinner, 80 SGD, with john, ricky, and tommy"
    # Example: "hotpot dinner, 80 SGD, paid by john, with john, ricky, and tommy"

    # Split by commas but be careful with participant lists
    parts = [p.strip() for p in text.split(",")]

    if len(parts) < 3:
        return None

    # First part is the title
    title = parts[0].strip()

    # Second part should be amount + currency
    amount_match = re.match(r"(\d+(?:\.\d+)?)\s*([A-Za-z]{3})", parts[1].strip())
    if not amount_match:
        return None

    amount = float(amount_match.group(1))
    currency = amount_match.group(2).upper()

    # Look for "paid by" and "with" clauses
    paid_by = None
    participants_text = ""

    remaining = ", ".join(parts[2:])

    # Check for "paid by X" pattern
    paid_by_match = re.search(r"paid\s+by\s+(\w+)", remaining, re.IGNORECASE)
    if paid_by_match:
        paid_by = paid_by_match.group(1).strip()
        remaining = re.sub(r"paid\s+by\s+\w+,?\s*", "", remaining, flags=re.IGNORECASE)

    # Extract participants after "with"
    with_match = re.search(r"with\s+(.+)$", remaining, re.IGNORECASE)
    if with_match:
        participants_text = with_match.group(1)
    else:
        return None

    # Parse participant names (handle "and", commas)
    participants_text = re.sub(r"\s+and\s+", ", ", participants_text, flags=re.IGNORECASE)
    participants = [
        p.strip().lower()
        for p in participants_text.split(",")
        if p.strip()
    ]

    if not participants:
        return None

    # If no "paid by" specified, assume first participant paid
    if not paid_by:
        paid_by = participants[0]
    else:
        paid_by = paid_by.lower()

    return ParsedExpense(
        title=title,
        amount=amount,
        currency=currency,
        paid_by=paid_by,
        participants=participants,
    )


def is_user_allowed(user_id: int) -> bool:
    """Check if user is allowed to use the bot."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not update.effective_user or not update.message:
        return

    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    welcome_text = """
Welcome to the Spliit Telegram Bot!

I help you manage expenses in your Spliit group directly from Telegram.

**Commands:**
/help - Show available commands
/group - Show group info and participants
/add - Add a new expense
/balance - Show current balances

**Example:**
`/add hotpot dinner, 80 SGD, with john, ricky, and tommy`

This will create an expense for "hotpot dinner" worth 80 SGD, split evenly between john, ricky, and tommy, with john as the payer.
    """
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not update.message:
        return

    help_text = """
**Spliit Bot Commands:**

/start - Show welcome message
/help - Show this help message
/group - Show current group info and participants
/balance - Show current balances

**Adding Expenses:**
`/add <title>, <amount> <currency>, with <participants>`

**Examples:**
- `/add hotpot dinner, 80 SGD, with john, ricky, and tommy`
- `/add groceries, 50 USD, paid by alice, with alice and bob`
- `/add taxi, 25 EUR, with john, mary, and peter`

**Notes:**
- If "paid by" is not specified, the first participant is assumed to be the payer
- Participant names are matched against your Spliit group members (case-insensitive)
- You'll get a confirmation message before the expense is created
    """
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /group command - show group info."""
    if not update.effective_user or not update.message:
        return

    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    if not SPLIIT_GROUP_ID:
        await update.message.reply_text(
            "No Spliit group configured. Please set SPLIIT_GROUP_ID in your .env file."
        )
        return

    await update.message.reply_text("Fetching group info...")

    group = await spliit_client.get_group()

    if not group:
        await update.message.reply_text(
            "Failed to fetch group info. Please check your configuration."
        )
        return

    participant_list = "\n".join(f"  - {p.name}" for p in group.participants)

    text = f"""
**Group:** {group.name}
**Currency:** {group.currency}
**Participants:**
{participant_list}

Group URL: {SPLIIT_BASE_URL}/groups/{SPLIIT_GROUP_ID}
    """
    await update.message.reply_text(text, parse_mode="Markdown")


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /balance command - show current balances."""
    if not update.effective_user or not update.message:
        return

    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    if not SPLIIT_GROUP_ID:
        await update.message.reply_text(
            "No Spliit group configured. Please set SPLIIT_GROUP_ID in your .env file."
        )
        return

    await update.message.reply_text("Fetching balances...")

    balances = await spliit_client.get_balances()

    if balances is None:
        await update.message.reply_text(
            "Failed to fetch balances. Please check your configuration."
        )
        return

    if not balances:
        await update.message.reply_text("No balances to show.")
        return

    # Format balances
    group = await spliit_client.get_group()
    currency = group.currency if group else "USD"

    lines = ["**Current Balances:**\n"]
    for balance in balances:
        participant_name = balance.get("participantName", "Unknown")
        amount = balance.get("balance", 0) / 100  # Convert from cents
        if amount > 0:
            lines.append(f"  {participant_name}: +{amount:.2f} {currency} (is owed)")
        elif amount < 0:
            lines.append(f"  {participant_name}: {amount:.2f} {currency} (owes)")
        else:
            lines.append(f"  {participant_name}: 0.00 {currency} (settled)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_expense_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add command - add a new expense with confirmation."""
    if not update.effective_user or not update.message:
        return

    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    if not SPLIIT_GROUP_ID:
        await update.message.reply_text(
            "No Spliit group configured. Please set SPLIIT_GROUP_ID in your .env file."
        )
        return

    text = update.message.text or ""
    expense = parse_expense_command(text)

    if not expense:
        await update.message.reply_text(
            "Could not parse expense. Please use the format:\n"
            "`/add <title>, <amount> <currency>, with <participants>`\n\n"
            "Example:\n"
            "`/add hotpot dinner, 80 SGD, with john, ricky, and tommy`",
            parse_mode="Markdown",
        )
        return

    # Fetch group to validate participants
    group = await spliit_client.get_group()
    if not group:
        await update.message.reply_text(
            "Failed to fetch group info. Please check your configuration."
        )
        return

    # Match participant names (case-insensitive)
    participant_map = {p.name.lower(): p for p in group.participants}

    # Validate payer
    payer = participant_map.get(expense.paid_by.lower())
    if not payer:
        available = ", ".join(p.name for p in group.participants)
        await update.message.reply_text(
            f"Could not find payer '{expense.paid_by}' in group.\n"
            f"Available participants: {available}"
        )
        return

    # Validate participants
    matched_participants = []
    unmatched = []
    for name in expense.participants:
        participant = participant_map.get(name.lower())
        if participant:
            matched_participants.append(participant)
        else:
            unmatched.append(name)

    if unmatched:
        available = ", ".join(p.name for p in group.participants)
        await update.message.reply_text(
            f"Could not find participants: {', '.join(unmatched)}\n"
            f"Available participants: {available}"
        )
        return

    # Create confirmation message
    participant_names = ", ".join(p.name for p in matched_participants)
    share_amount = expense.amount / len(matched_participants)

    confirmation_text = f"""
**Please confirm this expense:**

**Title:** {expense.title}
**Amount:** {expense.amount:.2f} {expense.currency}
**Paid by:** {payer.name}
**Split between:** {participant_names}
**Each pays:** {share_amount:.2f} {expense.currency}

Do you want to add this expense to Spliit?
    """

    # Store pending confirmation
    confirmation_key = f"{update.effective_user.id}_{update.message.message_id}"
    pending_confirmations[confirmation_key] = expense

    # Create inline keyboard for confirmation
    keyboard = [
        [
            InlineKeyboardButton("Confirm", callback_data=f"confirm_{confirmation_key}"),
            InlineKeyboardButton("Cancel", callback_data=f"cancel_{confirmation_key}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        confirmation_text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks for confirmation."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    data = query.data
    if data.startswith("confirm_"):
        confirmation_key = data[8:]  # Remove "confirm_" prefix
        expense = pending_confirmations.pop(confirmation_key, None)

        if not expense:
            await query.edit_message_text("This confirmation has expired. Please try again.")
            return

        # Fetch group to get participant IDs
        group = await spliit_client.get_group()
        if not group:
            await query.edit_message_text("Failed to fetch group info. Please try again.")
            return

        participant_map = {p.name.lower(): p for p in group.participants}

        # Get payer ID
        payer = participant_map.get(expense.paid_by.lower())
        if not payer:
            await query.edit_message_text(f"Could not find payer '{expense.paid_by}'.")
            return

        # Build paid_for list
        paid_for = []
        for name in expense.participants:
            participant = participant_map.get(name.lower())
            if participant:
                paid_for.append({"participantId": participant.id, "shares": 1})

        # Create expense in Spliit
        result = await spliit_client.create_expense(
            title=expense.title,
            amount=expense.amount,
            paid_by_id=payer.id,
            paid_for=paid_for,
        )

        if result:
            await query.edit_message_text(
                f"Expense '{expense.title}' for {expense.amount:.2f} {expense.currency} "
                f"has been added to Spliit!\n\n"
                f"View it at: {SPLIIT_BASE_URL}/groups/{SPLIIT_GROUP_ID}"
            )
        else:
            await query.edit_message_text(
                "Failed to create expense. Please try again or add it manually on Spliit."
            )

    elif data.startswith("cancel_"):
        confirmation_key = data[7:]  # Remove "cancel_" prefix
        pending_confirmations.pop(confirmation_key, None)
        await query.edit_message_text("Expense cancelled.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Exception while handling an update: {context.error}")


def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set!")
        return

    if not SPLIIT_GROUP_ID:
        logger.warning("SPLIIT_GROUP_ID is not set. Some features will be disabled.")

    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("group", group_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("add", add_expense_command))
    application.add_handler(CommandHandler("add_bill", add_expense_command))
    application.add_handler(CommandHandler("addbill", add_expense_command))

    # Add callback handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the bot
    logger.info("Starting Spliit Telegram Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
