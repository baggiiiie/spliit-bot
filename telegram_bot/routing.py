from __future__ import annotations

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from telegram_bot.add_flow import (
    add_cmd,
    cancel_interactive,
    interactive_amount,
    interactive_payees,
    interactive_payer,
    interactive_select_group,
    interactive_split_mode,
    interactive_split_values,
    interactive_title,
)
from telegram_bot.callbacks import button
from telegram_bot.commands import (
    balance_cmd,
    group_cmd,
    latest_cmd,
    settle_cmd,
    start,
    switch_cmd,
    undo_cmd,
)
from telegram_bot.constants import (
    AMOUNT,
    CB_PAYEE,
    CB_PAYER,
    CB_SELECT_GROUP,
    CB_SPLIT_MODE,
    PAYEES,
    PAYER,
    SELECT_GROUP,
    SPLIT_MODE,
    SPLIT_VALUES,
    TITLE,
)
from telegram_bot.voice_handler import voice_add_cmd


def build_handlers(app: Application) -> None:
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
            SELECT_GROUP: [
                CallbackQueryHandler(interactive_select_group, pattern=rf"^{CB_SELECT_GROUP}")
            ],
            TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_title),
                MessageHandler(filters.VOICE, voice_add_cmd),
            ],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_amount)],
            PAYER: [CallbackQueryHandler(interactive_payer, pattern=rf"^{CB_PAYER}")],
            PAYEES: [CallbackQueryHandler(interactive_payees, pattern=rf"^{CB_PAYEE}")],
            SPLIT_MODE: [
                CallbackQueryHandler(interactive_split_mode, pattern=rf"^{CB_SPLIT_MODE}")
            ],
            SPLIT_VALUES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_split_values)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_interactive)],
        allow_reentry=True,
    )
    app.add_handler(add_conv_handler)
    app.add_handler(CallbackQueryHandler(button))
