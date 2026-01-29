#!/usr/bin/env python3
"""Spliit Telegram Bot - Manage Spliit expenses via Telegram."""

import os
import re
import logging
from dataclasses import dataclass
from dotenv import load_dotenv
from spliit import Spliit
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SPLIIT_GROUP_ID = os.getenv("SPLIIT_GROUP_ID", "")

# Initialize Spliit client
spliit = Spliit(group_id=SPLIIT_GROUP_ID) if SPLIIT_GROUP_ID else None

# Pending confirmations: key -> (title, amount, paid_by_id, paid_for)
pending: dict[str, tuple] = {}


@dataclass
class ParsedExpense:
    title: str
    amount: float
    paid_by: str
    participants: list[str]


def parse_add_command(text: str) -> ParsedExpense | None:
    """Parse: /add title, amount currency, with p1, p2, and p3"""
    text = re.sub(r"^/add[-_]?bill?\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None

    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 3:
        return None

    title = parts[0]

    # Parse amount (ignore currency, Spliit uses group currency)
    amount_match = re.match(r"(\d+(?:\.\d+)?)", parts[1].strip())
    if not amount_match:
        return None
    amount = float(amount_match.group(1))

    # Parse participants from remaining parts
    remaining = ", ".join(parts[2:])

    # Check for "paid by X"
    paid_by = None
    paid_by_match = re.search(r"paid\s+by\s+(\w+)", remaining, re.IGNORECASE)
    if paid_by_match:
        paid_by = paid_by_match.group(1).strip()
        remaining = re.sub(r"paid\s+by\s+\w+,?\s*", "", remaining, flags=re.IGNORECASE)

    # Get participants after "with"
    with_match = re.search(r"with\s+(.+)$", remaining, re.IGNORECASE)
    if not with_match:
        return None

    participants_text = re.sub(
        r"\s+and\s+", ", ", with_match.group(1), flags=re.IGNORECASE
    )
    participants = [
        p.strip().lower() for p in participants_text.split(",") if p.strip()
    ]

    if not participants:
        return None

    if not paid_by:
        paid_by = participants[0]

    return ParsedExpense(
        title=title, amount=amount, paid_by=paid_by.lower(), participants=participants
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Spliit Bot\n\n"
        "Commands:\n"
        "/group - Show participants\n"
        "/balance - Show balances\n"
        "/add title, amount, with participants\n\n"
        "Example:\n"
        "`/add dinner, 80, with john, mary, and tom`",
        parse_mode="Markdown",
    )


def get_balances(group_id: str) -> dict:
    """Fetch balances from Spliit API."""
    import requests
    import json

    params_input = {"0": {"json": {"groupId": group_id}}}
    params = {"batch": "1", "input": json.dumps(params_input)}
    response = requests.get(
        "https://spliit.app/api/trpc/groups.balances.list", params=params
    )
    return response.json()[0]["result"]["data"]["json"]


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not spliit:
        await update.message.reply_text("SPLIIT_GROUP_ID not configured.")
        return

    try:
        group = spliit.get_group()
        balance_data = get_balances(SPLIIT_GROUP_ID)
        balances = balance_data["balances"]
        reimbursements = balance_data["reimbursements"]

        # Map participant IDs to names
        id_to_name = {p["id"]: p["name"] for p in group["participants"]}
        currency = group["currency"]

        # Format balances
        lines = [f"**{group['name']}** Balances\n"]
        for pid, data in balances.items():
            name = id_to_name.get(pid, pid)
            total = data["total"] / 100
            if total > 0:
                lines.append(f"• {name}: +{currency}{total:.2f}")
            elif total < 0:
                lines.append(f"• {name}: {currency}{total:.2f}")
            else:
                lines.append(f"• {name}: {currency}0.00")

        # Format suggested reimbursements
        if reimbursements:
            lines.append("\n**Suggested Payments:**")
            for r in reimbursements:
                from_name = id_to_name.get(r["from"], r["from"])
                to_name = id_to_name.get(r["to"], r["to"])
                amount = r["amount"] / 100
                lines.append(f"• {from_name} → {to_name}: {currency}{amount:.2f}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to get balances: {e}")
        await update.message.reply_text(f"Error: {e}")


async def group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not spliit:
        await update.message.reply_text("SPLIIT_GROUP_ID not configured.")
        return

    try:
        group = spliit.get_group()
        names = [p["name"] for p in group["participants"]]
        await update.message.reply_text(
            f"**{group['name']}** ({group['currency']})\n\nParticipants:\n"
            + "\n".join(f"- {n}" for n in names),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Failed to get group: {e}")
        await update.message.reply_text(f"Error: {e}")


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not spliit:
        await update.message.reply_text("SPLIIT_GROUP_ID not configured.")
        return

    expense = parse_add_command(update.message.text or "")
    if not expense:
        await update.message.reply_text(
            "Format: `/add title, amount, with p1, p2, and p3`",
            parse_mode="Markdown",
        )
        return

    try:
        participants_map = spliit.get_participants()
    except Exception as e:
        await update.message.reply_text(f"Error fetching participants: {e}")
        return

    # Match names (case-insensitive)
    name_map = {n.lower(): (n, pid) for n, pid in participants_map.items()}

    payer = name_map.get(expense.paid_by)
    if not payer:
        await update.message.reply_text(
            f"Payer '{expense.paid_by}' not found.\nAvailable: {', '.join(participants_map.keys())}"
        )
        return

    matched = []
    for name in expense.participants:
        p = name_map.get(name)
        if not p:
            await update.message.reply_text(
                f"'{name}' not found.\nAvailable: {', '.join(participants_map.keys())}"
            )
            return
        matched.append(p)

    # Store for confirmation
    key = f"{update.effective_user.id}_{update.message.message_id}"
    amount_cents = int(expense.amount * 100)
    paid_for = [(pid, 1) for _, pid in matched]
    pending[key] = (expense.title, amount_cents, payer[1], paid_for)

    share = expense.amount / len(matched)
    keyboard = [
        [
            InlineKeyboardButton("Confirm", callback_data=f"yes_{key}"),
            InlineKeyboardButton("Cancel", callback_data=f"no_{key}"),
        ]
    ]

    await update.message.reply_text(
        f"**{expense.title}**\n"
        f"Amount: {expense.amount:.2f}\n"
        f"Paid by: {payer[0]}\n"
        f"Split: {', '.join(n for n, _ in matched)}\n"
        f"Each: {share:.2f}\n\n"
        f"Confirm?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if data.startswith("yes_"):
        key = data[4:]
        info = pending.pop(key, None)
        if not info:
            await query.edit_message_text("Expired. Try again.")
            return

        title, amount, paid_by_id, paid_for = info
        try:
            spliit.add_expense(
                title=title, paid_by=paid_by_id, paid_for=paid_for, amount=amount
            )
            await query.edit_message_text(f"Added: {title}")
        except Exception as e:
            logger.error(f"Failed to add expense: {e}")
            await query.edit_message_text(f"Failed: {e}")

    elif data.startswith("no_"):
        key = data[3:]
        pending.pop(key, None)
        await query.edit_message_text("Cancelled.")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("group", group_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("addbill", add_cmd))
    app.add_handler(CallbackQueryHandler(button))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
