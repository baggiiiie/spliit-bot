#!/usr/bin/env python3
"""Spliit Telegram Bot - Manage Spliit expenses via Telegram."""

from __future__ import annotations

import traceback

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import (
    ADMIN_TELEGRAM_USER_ID,
    AMOUNT,
    BOT_MODE,
    HEALTH_HTTP_PORT,
    PAYEES,
    PAYER,
    SELECT_GROUP,
    TELEGRAM_BOT_TOKEN,
    TITLE,
    WEBHOOK_PORT,
    WEBHOOK_SECRET,
    WEBHOOK_URL,
    logger,
)
from handlers import (
    add_cmd,
    balance_cmd,
    button,
    cancel_interactive,
    group_cmd,
    interactive_amount,
    interactive_payees,
    interactive_payer,
    interactive_select_group,
    interactive_title,
    latest_cmd,
    settle_cmd,
    start,
    switch_cmd,
    undo_cmd,
)
from health_http import start_background_health_server


async def log_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.from_user:
        logger.info(
            f"chat_id={update.message.chat_id} "
            f"user_id={update.message.from_user.id} "
            f"message_id={update.message.message_id}"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.error:
        return
    tb = "".join(traceback.format_exception(context.error))
    logger.error(f"Exception:\n{tb}")
    if ADMIN_TELEGRAM_USER_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_TELEGRAM_USER_ID,
                text=f"⚠️ Bot error:\n<pre>{tb}</pre>",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    if HEALTH_HTTP_PORT > 0:
        if BOT_MODE == "webhook" and WEBHOOK_PORT == HEALTH_HTTP_PORT:
            logger.error(
                "HEALTH_HTTP_PORT cannot match WEBHOOK_PORT; use polling for ONCE or "
                "set WEBHOOK_PORT to a different port than HEALTH_HTTP_PORT"
            )
            return
        start_background_health_server(HEALTH_HTTP_PORT)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, log_message), group=-1)
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("group", group_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("settle", settle_cmd))
    app.add_handler(CommandHandler("undo", undo_cmd))
    app.add_handler(CommandHandler("latest", latest_cmd))
    app.add_handler(CommandHandler("switch", switch_cmd))

    add_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_cmd)],
        states={
            SELECT_GROUP: [CallbackQueryHandler(interactive_select_group, pattern=r"^selgrp_")],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_title)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_amount)],
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

        logger.info(f"Bot starting in webhook mode on port {WEBHOOK_PORT}...")
        app.run_webhook(
            listen="0.0.0.0",
            port=WEBHOOK_PORT,
            url_path="/webhook",
            webhook_url=f"{WEBHOOK_URL.rstrip('/')}/webhook",
            secret_token=WEBHOOK_SECRET or None,
        )
    else:
        logger.info("Bot starting in polling mode...")
        app.run_polling()


if __name__ == "__main__":
    main()
