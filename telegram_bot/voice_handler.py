"""Voice message handler that transcribes and forwards to the /add flow."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from llm.voice import transcribe_voice
from spliit_integration.gateway import gateway
from telegram_bot.access import is_allowed_chat, is_dm
from telegram_bot.add_flow import enter_add_with_text
from telegram_bot.group_picker import DM_NO_GROUP_MSG, NO_GROUP_MSG, resolve_group
from telegram_bot.session import Session

logger = logging.getLogger(__name__)


async def voice_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not update.message or not update.message.voice or not update.effective_user:
        return None
    if not is_allowed_chat(update):
        return None

    Session(context.user_data, context.bot_data).draft = None
    group_id = resolve_group(update, context.user_data)
    if not group_id:
        await update.message.reply_text(
            DM_NO_GROUP_MSG if is_dm(update) else NO_GROUP_MSG,
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    try:
        participant_names = list(gateway.group(group_id).directory.participants_map)
    except Exception as error:
        await update.message.reply_text(
            f"Error: {error}",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    voice_file = await update.message.voice.get_file()
    voice_bytes = await voice_file.download_as_bytearray()
    transcript = await transcribe_voice(
        bytes(voice_bytes),
        prompt="Participants: " + ", ".join(participant_names) + ".",
    )
    if not transcript:
        await update.message.reply_text(
            "Couldn't understand the voice message. Please type the expense instead.",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END

    logger.info("Voice transcribed: %s", transcript)
    await update.message.reply_text(
        f"Transcribed voice message: {transcript}",
        reply_to_message_id=update.message.message_id,
    )
    return await enter_add_with_text(update, context, transcript, group_id=group_id)
