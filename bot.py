#!/usr/bin/env python3
"""Spliit Telegram Bot - Manage Spliit expenses via Telegram."""

from __future__ import annotations

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import (
    AMOUNT,
    BOT_MODE,
    PAYEES,
    PAYER,
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
    interactive_title,
    start,
)


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
