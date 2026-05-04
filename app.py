#!/usr/bin/env python3
"""Spliit Telegram Bot application wiring."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from config import (
    BOT_MODE,
    HEALTH_HTTP_PORT,
    TELEGRAM_BOT_TOKEN,
    WEBHOOK_PORT,
    WEBHOOK_SECRET,
    WEBHOOK_URL,
)
from infra.health_http import start_background_health_server
from infra.logging import logger
from telegram_bot.admin import error_handler
from telegram_bot.routing import build_handlers


async def log_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.from_user:
        logger.info(
            f"chat_id={update.message.chat_id} "
            f"user_id={update.message.from_user.id} "
            f"message_id={update.message.message_id}"
        )


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
    build_handlers(app)

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
