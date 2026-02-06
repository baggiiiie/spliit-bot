#!/usr/bin/env python3
"""Spliit Telegram Bot - Manage Spliit expenses via Telegram."""

from __future__ import annotations

import os
import re
import json
import logging
import html
import subprocess
from dataclasses import dataclass
from typing import Any
from dotenv import load_dotenv
from spliit import Spliit
from telegram import Message, Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
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
OPENCODE_CLI = os.getenv("OPENCODE_CLI", "opencode")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "opencode/kimi-k2.5-free")

BOT_MODE = os.getenv("BOT_MODE", "polling").lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

spliit: Spliit | None = Spliit(group_id=SPLIIT_GROUP_ID) if SPLIIT_GROUP_ID else None

PROMPT_PATH: str = os.path.join(os.path.dirname(__file__), "prompt.txt")
with open(PROMPT_PATH) as f:
    PROMPT_TEMPLATE: str = f.read()

USERS_JSON_PATH: str = os.path.join(os.path.dirname(__file__), "users.json")
try:
    with open(USERS_JSON_PATH) as f:
        SPLIIT_TO_TELEGRAM: dict[str, str] = json.load(f)
except Exception:
    SPLIIT_TO_TELEGRAM = {}

PaidFor = list[tuple[str, int]]
PendingExpense = tuple[str, int, str, PaidFor, str]

pending: dict[str, PendingExpense] = {}

TITLE, AMOUNT, PAYER, PAYEES = range(4)


def is_allowed_chat(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    user_id = update.effective_user.id if update.effective_user else None
    return str(chat_id) == ALLOWED_CHAT_ID or str(user_id) == ALLOWED_USER_ID


def id_to_name_map(client: Spliit) -> tuple[dict[str, str], str]:
    group = client.get_group()
    return {p["id"]: p["name"] for p in group["participants"]}, group["currency"]


def participant_keyboard(
    participants: dict[str, str],
    prefix: str,
    selected: set[str] | None = None,
    done_btn: tuple[str, str] | None = None,
) -> InlineKeyboardMarkup:
    selected = selected or set()
    rows = [
        [InlineKeyboardButton(
            f"{'✓ ' if pid in selected else ''}{name}",
            callback_data=f"{prefix}{pid}",
        )]
        for name, pid in participants.items()
    ]
    if done_btn:
        all_selected = selected == set(pid for _, pid in participants.items())
        rows.append([
            InlineKeyboardButton(
                "Deselect All" if all_selected else "Select All",
                callback_data=f"{prefix}all",
            ),
            InlineKeyboardButton(done_btn[0], callback_data=done_btn[1]),
        ])
    return InlineKeyboardMarkup(rows)


def confirm_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm", callback_data=f"yes_{key}"),
        InlineKeyboardButton("Cancel", callback_data=f"no_{key}"),
    ]])


def format_confirmation(title: str, amount: float, payer: str, payees: list[str]) -> str:
    share = amount / len(payees)
    return (
        f"**{title}**\n"
        f"Amount: {amount:.2f}\n"
        f"Paid by: {payer}\n"
        f"Split: {', '.join(payees)}\n"
        f"Each: {share:.2f}\n\n"
        f"Confirm?"
    )


def tg_display_name(update: Update) -> str:
    u = update.effective_user
    if not u:
        return "unknown"
    return u.first_name or u.username or "unknown"


async def build_mention(name: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    tg_id = SPLIIT_TO_TELEGRAM.get(name.lower())
    if not tg_id:
        return name
    try:
        chat = await context.bot.get_chat(int(tg_id))
        if chat.username:
            return f"@{chat.username}"
        display = chat.first_name or name
        return f'<a href="tg://user?id={tg_id}">{display}</a>'
    except Exception:
        return f'<a href="tg://user?id={tg_id}">{name}</a>'


@dataclass
class ParsedExpense:
    title: str
    amount: float
    participants: list[str] | None = None


def parse_add_command(
    text: str, known_participants: list[str] | None = None
) -> ParsedExpense | None:
    text = re.sub(r"^/add\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None

    parts = [p.strip() for p in text.split(",", 2)]
    if len(parts) < 2:
        return None

    title = parts[0]
    amount_match = re.match(r"(\d+(?:\.\d+)?)", parts[1].strip())
    if not amount_match:
        return None
    amount = float(amount_match.group(1))

    if len(parts) < 3 or not known_participants:
        return ParsedExpense(title=title, amount=amount)

    names_text = parts[2].lower()
    matched = [
        name for name in known_participants if name.lower() in names_text
    ]
    if not matched:
        return ParsedExpense(title=title, amount=amount)

    return ParsedExpense(
        title=title, amount=amount, participants=[n.lower() for n in matched]
    )


def parse_with_llm(
    text: str, participant_names: list[str]
) -> ParsedExpense | str | None:
    prompt = PROMPT_TEMPLATE.format(
        participants=", ".join(participant_names),
        message=text,
    )

    try:
        result = subprocess.run(
            [OPENCODE_CLI, "run", "-m", OPENCODE_MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"opencode CLI failed: {result.stderr}")
            return None
        raw = result.stdout.strip()

        json_match = re.search(r"\{[^}]+\}", raw)
        if not json_match:
            return None
        data = json.loads(json_match.group())

        if "error" in data:
            return "Could not understand the expense. Please use the format:\n`/add $title, $amount, with p1, p2, and p3`"

        title = data.get("title")
        amount = data.get("amount")
        if not title or not isinstance(amount, (int, float)) or amount <= 0:
            return None

        participants = data.get("participants")
        if isinstance(participants, list) and participants:
            known_lower = {n.lower(): n for n in participant_names}
            matched = [known_lower[p.lower()] for p in participants if p.lower() in known_lower]
            if matched:
                return ParsedExpense(title=title, amount=float(amount), participants=[n.lower() for n in matched])

        return ParsedExpense(title=title, amount=float(amount))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"LLM JSON parse failed: {e}")
        return None
    except Exception as e:
        logger.error(f"LLM parse failed: {e}")
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    await update.message.reply_text(
        "baggiiiie's Spliit Bot\n\n"
        "url: https://spliit.app/groups/WF\_-cIdW0KrDhsIal1uhI/\n"
        "Commands:\n"
        "/group - Show participants\n"
        "/balance - Show balances\n"
        "/add title, amount, with participants\n\n"
        "Example:\n"
        "`/add` (interactive)\n"
        "`/add $title, $amount` (interactive)\n"
        "`/add $title, $amount, baggie neo yoga ricky`\n"
        "↳ bot will ask who paid",
        parse_mode="Markdown",
    )


def get_balances(group_id: str) -> dict[str, Any]:
    import requests

    params_input = {"0": {"json": {"groupId": group_id}}}
    params = {"batch": "1", "input": json.dumps(params_input)}
    response = requests.get(
        "https://spliit.app/api/trpc/groups.balances.list", params=params
    )
    return response.json()[0]["result"]["data"]["json"]


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
        return
    if not spliit:
        await update.message.reply_text("SPLIIT_GROUP_ID not configured.")
        return

    try:
        id_name, currency = id_to_name_map(spliit)
        balance_data = get_balances(SPLIIT_GROUP_ID)
        balances = balance_data["balances"]
        reimbursements = balance_data["reimbursements"]

        group = spliit.get_group()
        lines = [f"**{group['name']}** Balances\n"]
        for pid, data in balances.items():
            name = id_name.get(pid, pid)
            total = data["total"] / 100
            if total > 0:
                lines.append(f"- {name}: +{currency}{total:.2f}")
            elif total < 0:
                lines.append(f"- {name}: {currency}{total:.2f}")
            else:
                lines.append(f"- {name}: {currency}0.00")

        if reimbursements:
            lines.append("\n**Suggested Payments:**")
            for r in reimbursements:
                from_name = id_name.get(r["from"], r["from"])
                to_name = id_name.get(r["to"], r["to"])
                amount = r["amount"] / 100
                lines.append(f"- {from_name} -> {to_name}: {currency}{amount:.2f}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to get balances: {e}")
        await update.message.reply_text(f"Error: {e}")


async def group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_chat(update) or not update.message:
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


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not is_allowed_chat(update) or not update.message or not update.effective_user:
        return ConversationHandler.END
    if not spliit:
        await update.message.reply_text("SPLIIT_GROUP_ID not configured.")
        return ConversationHandler.END

    text = (update.message.text or "").strip()

    if text == "/add":
        await update.message.reply_text(
            "Enter expense title:",
            reply_markup=ForceReply(
                selective=True, input_field_placeholder="e.g. Dinner"
            ),
        )
        return TITLE

    assert context.user_data is not None

    try:
        participants_map = spliit.get_participants()
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

    context.user_data["participants_map"] = participants_map
    participant_names = list(participants_map.keys())

    expense = parse_add_command(text, participant_names)

    if not expense:
        raw_text = re.sub(r"^/add[-_]?bill?\s*", "", text, flags=re.IGNORECASE).strip()
        llm_result = parse_with_llm(raw_text, participant_names)
        if isinstance(llm_result, str):
            await update.message.reply_text(llm_result, parse_mode="Markdown")
            return ConversationHandler.END
        if llm_result:
            expense = llm_result
            logger.info(f"LLM parsed: {expense}")

    if not expense:
        await update.message.reply_text(
            "Format: `/add title, amount, names`",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    context.user_data["expense_title"] = expense.title
    context.user_data["expense_amount"] = expense.amount

    if expense.participants is None:
        await update.message.reply_text(
            f"*{expense.title}* — {expense.amount:.2f}\n\nWho paid?",
            parse_mode="Markdown",
            reply_markup=participant_keyboard(participants_map, "payer_"),
        )
        return PAYER

    name_map = {n.lower(): (n, pid) for n, pid in participants_map.items()}
    matched = [(n, pid) for n, pid in ((name, name_map.get(name)) for name in expense.participants) if pid]

    context.user_data["selected_payees"] = [pid for _, (_, pid) in matched]

    await update.message.reply_text(
        f"*{expense.title}* — {expense.amount:.2f}\n"
        f"Split: {', '.join(n for (n, _) in matched)}\n\nWho paid?",
        parse_mode="Markdown",
        reply_markup=participant_keyboard(participants_map, "payer_"),
    )
    return PAYER


async def interactive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text and context.user_data is not None
    context.user_data["expense_title"] = update.message.text.strip()
    await update.message.reply_text(
        "Enter amount:",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 50.00"),
    )
    return AMOUNT


async def interactive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text and context.user_data is not None
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

    assert spliit
    try:
        participants_map = spliit.get_participants()
        context.user_data["participants_map"] = participants_map
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

    await update.message.reply_text(
        "Who paid?",
        reply_markup=participant_keyboard(participants_map, "payer_"),
    )
    return PAYER


async def interactive_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and context.user_data is not None
    await query.answer()

    payer_id = query.data[6:]
    participants_map = context.user_data["participants_map"]
    reverse = {pid: name for name, pid in participants_map.items()}

    context.user_data["payer_id"] = payer_id
    context.user_data["payer_name"] = reverse[payer_id]

    pre_selected = context.user_data.get("selected_payees", [])
    if pre_selected:
        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        paid_for: PaidFor = [(pid, 1) for pid in pre_selected]
        payee_names = [reverse[pid] for pid in pre_selected]

        assert query.message
        key = f"{update.effective_user.id}_{query.message.message_id}"
        pending[key] = (title, int(amount * 100), payer_id, paid_for, tg_display_name(update))

        await query.edit_message_text(
            format_confirmation(title, amount, reverse[payer_id], payee_names),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard(key),
        )
        return ConversationHandler.END

    context.user_data["selected_payees"] = []
    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=participant_keyboard(
            participants_map, "payee_", done_btn=("< Done >", "payee_done")
        ),
    )
    return PAYEES


async def interactive_payees(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data and update.effective_user and context.user_data is not None
    await query.answer()

    data: str = query.data
    if data == "payee_done":
        selected: list[str] = context.user_data.get("selected_payees", [])
        if not selected:
            await query.answer("Select at least one person", show_alert=True)
            return PAYEES

        title = context.user_data["expense_title"]
        amount = context.user_data["expense_amount"]
        payer_id = context.user_data["payer_id"]
        payer_name = context.user_data["payer_name"]
        participants_map = context.user_data["participants_map"]
        reverse = {pid: name for name, pid in participants_map.items()}

        paid_for: PaidFor = [(pid, 1) for pid in selected]
        payee_names = [reverse[pid] for pid in selected]

        assert query.message
        key = f"{update.effective_user.id}_{query.message.message_id}"
        pending[key] = (title, int(amount * 100), payer_id, paid_for, tg_display_name(update))

        await query.edit_message_text(
            format_confirmation(title, amount, payer_name, payee_names),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard(key),
        )
        return ConversationHandler.END

    payee_id = data[6:]
    selected = context.user_data.get("selected_payees", [])
    if payee_id == "all":
        all_ids = list(participants_map.values())
        if set(selected) == set(all_ids):
            selected = []
        else:
            selected = list(all_ids)
    elif payee_id in selected:
        selected.remove(payee_id)
    else:
        selected.append(payee_id)
    context.user_data["selected_payees"] = selected

    participants_map = context.user_data["participants_map"]
    await query.edit_message_text(
        "Select who to split with (tap to toggle, then Done):",
        reply_markup=participant_keyboard(
            participants_map, "payee_", set(selected), done_btn=("✓ Done", "payee_done")
        ),
    )
    return PAYEES


async def cancel_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query
    await query.answer()

    data: str = query.data or ""
    if data.startswith("yes_"):
        key = data[4:]
        info = pending.pop(key, None)
        if not info:
            await query.edit_message_text("Expired. Try again.")
            return

        title, amount, paid_by_id, paid_for, tg_name = info
        expense_title = f"[telebot-{tg_name}] {title}"
        try:
            assert spliit
            spliit.add_expense(
                title=expense_title,
                paid_by=paid_by_id,
                paid_for=paid_for,
                amount=amount,
            )
            await query.edit_message_text(f"Added: {title}")

            id_name, currency = id_to_name_map(spliit)
            payer_name = id_name.get(paid_by_id, "Unknown")
            payee_names = [id_name.get(pid, "Unknown") for pid, _ in paid_for]

            involved = set(payee_names + [payer_name])
            mentions = [await build_mention(n, context) for n in involved]

            amount_display = amount / 100
            share = amount_display / len(payee_names)
            msg = (
                f"💸 <b>{html.escape(title)}</b> added\n"
                f"Amount: {html.escape(currency)}{amount_display:.2f}\n"
                f"Paid by: {html.escape(payer_name)}\n"
                f"Split ({html.escape(currency)}{share:.2f} each): {html.escape(', '.join(payee_names))}\n\n"
                f"👋 {' '.join(mentions)}"
            )
            assert isinstance(query.message, Message)
            await query.message.reply_text(msg, parse_mode="HTML")
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
        entry_points=[CommandHandler("add", add_cmd)],
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

    if BOT_MODE == "webhook":
        if not WEBHOOK_URL:
            logger.error("WEBHOOK_URL not set for webhook mode")
            return

        webhook_path = "/webhook"
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}{webhook_path}"

        logger.info(f"Bot starting in webhook mode on port {WEBHOOK_PORT}...")
        app.run_webhook(
            listen="0.0.0.0",
            port=WEBHOOK_PORT,
            url_path=webhook_path,
            webhook_url=full_webhook_url,
            secret_token=WEBHOOK_SECRET or None,
        )
    else:
        logger.info("Bot starting in polling mode...")
        app.run_polling()


if __name__ == "__main__":
    main()
