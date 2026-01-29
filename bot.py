#!/usr/bin/env python3
"""Spliit Telegram Bot - Manage Spliit expenses via Telegram."""

import os
import re
import logging
from dataclasses import dataclass
from dotenv import load_dotenv
from spliit import Spliit
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SPLIIT_GROUP_ID = os.getenv("SPLIIT_GROUP_ID", "")
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID", "")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "")

# Initialize Spliit client
spliit = Spliit(group_id=SPLIIT_GROUP_ID) if SPLIIT_GROUP_ID else None

# Pending confirmations: key -> (title, amount, paid_by_id, paid_for)
pending: dict[str, tuple] = {}


def is_allowed_chat(update: Update) -> bool:
    """Check if the update is from the allowed chat."""
    return (
        str(update.effective_chat.id) == ALLOWED_CHAT_ID
        or str(update.effective_user.id) == ALLOWED_USER_ID
    )


# Conversation states for interactive /add
TITLE, AMOUNT, PAYER, PAYEES = range(4)


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
    if not is_allowed_chat(update):
        return
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
    if not is_allowed_chat(update):
        return
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
                lines.append(f"- {name}: +{currency}{total:.2f}")
            elif total < 0:
                lines.append(f"- {name}: {currency}{total:.2f}")
            else:
                lines.append(f"- {name}: {currency}0.00")

        # Format suggested reimbursements
        if reimbursements:
            lines.append("\n**Suggested Payments:**")
            for r in reimbursements:
                from_name = id_to_name.get(r["from"], r["from"])
                to_name = id_to_name.get(r["to"], r["to"])
                amount = r["amount"] / 100
                lines.append(f"- {from_name} -> {to_name}: {currency}{amount:.2f}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to get balances: {e}")
        await update.message.reply_text(f"Error: {e}")


async def group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update):
        return
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


def parse_partial_add(text: str) -> tuple[str, float] | None:
    """Parse: /add title, amount (without participants)"""
    text = re.sub(r"^/add[-_]?bill?\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None

    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 2:
        return None

    title = parts[0]
    amount_match = re.match(r"(\d+(?:\.\d+)?)", parts[1].strip())
    if not amount_match:
        return None

    return (title, float(amount_match.group(1)))


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not is_allowed_chat(update):
        return ConversationHandler.END
    if not spliit:
        await update.message.reply_text("SPLIIT_GROUP_ID not configured.")
        return ConversationHandler.END

    text = (update.message.text or "").strip()

    # Check if command has no arguments -> full interactive mode
    if text in ("/add", "/addbill"):
        await update.message.reply_text(
            "Enter expense title:",
            reply_markup=ForceReply(
                selective=True, input_field_placeholder="e.g. Dinner"
            ),
        )
        return TITLE

    # Check for partial format: /add title, amount (no participants)
    partial = parse_partial_add(text)
    if partial:
        title, amount = partial
        context.user_data["expense_title"] = title
        context.user_data["expense_amount"] = amount

        try:
            participants_map = spliit.get_participants()
            context.user_data["participants_map"] = participants_map
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"payer_{pid}")]
            for name, pid in participants_map.items()
        ]
        await update.message.reply_text(
            f"*{title}* - {amount:.2f}\n\nWho paid?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return PAYER

    expense = parse_add_command(text)
    if not expense:
        await update.message.reply_text(
            "Format: `/add title, amount, with p1, p2, and p3`",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    try:
        participants_map = spliit.get_participants()
    except Exception as e:
        await update.message.reply_text(f"Error fetching participants: {e}")
        return ConversationHandler.END

    # Match names (case-insensitive)
    name_map = {n.lower(): (n, pid) for n, pid in participants_map.items()}

    payer = name_map.get(expense.paid_by)
    if not payer:
        await update.message.reply_text(
            f"whodat? '{expense.paid_by}' not found.\nAvailable: {', '.join(participants_map.keys())}"
        )
        return ConversationHandler.END

    matched = []
    for name in expense.participants:
        p = name_map.get(name)
        if not p:
            await update.message.reply_text(
                f"'{name}' not found.\nAvailable: {', '.join(participants_map.keys())}"
            )
            return ConversationHandler.END
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
    return ConversationHandler.END


async def interactive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["expense_title"] = update.message.text.strip()
    await update.message.reply_text(
        "Enter amount:",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
    )
    return AMOUNT


async def interactive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    match = re.match(r"(\d+(?:\.\d+)?)", text)
    if not match:
        await update.message.reply_text(
            "Invalid amount. Enter a number:",
            reply_markup=ForceReply(
                selective=True, input_field_placeholder="e.g. 50.00"
            ),
        )
        return AMOUNT

    context.user_data["expense_amount"] = float(match.group(1))

    try:
        participants_map = spliit.get_participants()
        context.user_data["participants_map"] = participants_map
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"payer_{pid}")]
        for name, pid in participants_map.items()
    ]
    await update.message.reply_text(
        "Who paid?", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PAYER


async def interactive_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    payer_id = query.data[6:]  # Remove "payer_" prefix
    participants_map = context.user_data["participants_map"]
    id_to_name = {pid: name for name, pid in participants_map.items()}

    context.user_data["payer_id"] = payer_id
    context.user_data["payer_name"] = id_to_name[payer_id]
    context.user_data["selected_payees"] = []

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"payee_{pid}")]
        for name, pid in participants_map.items()
    ]
    keyboard.append([InlineKeyboardButton("< Done >", callback_data="payee_done")])

    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PAYEES


async def interactive_payees(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "payee_done":
        selected = context.user_data.get("selected_payees", [])
        if not selected:
            await query.answer("Select at least one person", show_alert=True)
            return PAYEES

        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        payer_id = context.user_data["payer_id"]
        payer_name = context.user_data["payer_name"]
        participants_map = context.user_data["participants_map"]
        id_to_name = {pid: name for name, pid in participants_map.items()}

        paid_for = [(pid, 1) for pid in selected]
        payee_names = [id_to_name[pid] for pid in selected]

        key = f"{update.effective_user.id}_{query.message.message_id}"
        pending[key] = (title, int(amount * 100), payer_id, paid_for)

        share = amount / len(selected)
        keyboard = [
            [
                InlineKeyboardButton("Confirm", callback_data=f"yes_{key}"),
                InlineKeyboardButton("Cancel", callback_data=f"no_{key}"),
            ]
        ]

        await query.edit_message_text(
            f"**{title}**\n"
            f"Amount: {amount:.2f}\n"
            f"Paid by: {payer_name}\n"
            f"Split: {', '.join(payee_names)}\n"
            f"Each: {share:.2f}\n\n"
            f"Confirm?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    # Toggle payee selection
    payee_id = data[6:]  # Remove "payee_" prefix
    selected = context.user_data.get("selected_payees", [])
    if payee_id in selected:
        selected.remove(payee_id)
    else:
        selected.append(payee_id)
    context.user_data["selected_payees"] = selected

    # Rebuild keyboard with checkmarks
    participants_map = context.user_data["participants_map"]
    keyboard = []
    for name, pid in participants_map.items():
        mark = "✓ " if pid in selected else ""
        keyboard.append(
            [InlineKeyboardButton(f"{mark}{name}", callback_data=f"payee_{pid}")]
        )
    keyboard.append([InlineKeyboardButton("✓ Done", callback_data="payee_done")])

    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PAYEES


async def cancel_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


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

    add_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_cmd),
            CommandHandler("addbill", add_cmd),
        ],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_title)],
            AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_amount)
            ],
            PAYER: [CallbackQueryHandler(interactive_payer, pattern=r"^payer_")],
            PAYEES: [CallbackQueryHandler(interactive_payees, pattern=r"^payee_")],
        },
        fallbacks=[CommandHandler("cancel", cancel_interactive)],
    )
    app.add_handler(add_conv_handler)
    app.add_handler(CallbackQueryHandler(button))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
