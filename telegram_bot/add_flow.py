"""The /add conversation flow (multi-step expense creation)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from telegram import CallbackQuery, Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from domain.expense import (
    Ended,
    ExpenseDraft,
    LLMParsedExpense,
    NeedsInput,
    Outcome,
    ParseFailure,
    ReadyToConfirm,
    Rejected,
    apply_amount,
    apply_payer,
    apply_split_mode,
    apply_split_values,
    apply_title,
    complete_payees,
    start_draft,
    start_from_parsed,
    toggle_all_payees,
    toggle_payee,
)
from llm.parser import parse_add_text
from spliit_integration.gateway import gateway
from telegram_bot.access import is_allowed_chat, is_dm, tg_display_name
from telegram_bot.admin import notify_admin_llm_error
from telegram_bot.constants import (
    CB_PAYEE,
    CB_PAYEE_ALL,
    CB_PAYEE_DONE,
    CB_PAYER,
    CB_SELECT_GROUP,
    CB_SPLIT_MODE,
    PAYEES,
    SELECT_GROUP,
)
from telegram_bot.group_picker import (
    NO_GROUP_MSG,
    configured_group_ids,
    group_name,
    group_picker_options,
    resolve_group,
)
from telegram_bot.keyboards import group_picker_keyboard
from telegram_bot.session import Session
from telegram_bot.ui import (
    ConversationReply,
    MessageAction,
    error_reply,
    expense_confirmation_reply,
    expense_prompt_reply,
    invalid_amount_reply,
    split_values_retry_reply,
)

_FORMAT_HELP = "Format: `/add title, amount` or describe the expense in plain text."


@dataclass(frozen=True, slots=True)
class AddContext:
    message: Message
    context: ContextTypes.DEFAULT_TYPE
    session: Session
    user_id: int
    tg_name: str
    group_id: str
    query: CallbackQuery | None = None


def _add_context(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    group_id: str | None = None,
    query: CallbackQuery | None = None,
    message: Message | None = None,
) -> AddContext:
    assert update.effective_user is not None
    if message is not None:
        resolved_message = message
    elif query is not None:
        assert query.message is not None
        resolved_message = cast(Message, query.message)
    else:
        assert update.message is not None
        resolved_message = update.message
    resolved_group_id = group_id or resolve_group(update, context.user_data)
    assert resolved_group_id is not None
    return AddContext(
        message=resolved_message,
        context=context,
        session=Session(context.user_data, context.bot_data),
        user_id=update.effective_user.id,
        tg_name=tg_display_name(update),
        group_id=resolved_group_id,
        query=query,
    )


def _command_payload(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if not parts or parts[0].split("@", 1)[0].lower() != "/add":
        return text.strip()
    if len(parts) == 1:
        return None
    return parts[1].strip()


def _parse_title_amount(text: str) -> LLMParsedExpense | None:
    title, separator, amount = text.partition(",")
    if not separator:
        return None
    title = title.strip()
    amount = amount.strip()
    if not title or not amount:
        return None
    try:
        parsed_amount = float(amount)
    except ValueError:
        return None
    return LLMParsedExpense(title=title, amount=parsed_amount)


def _outcome_to_reply(ctx: AddContext, draft: ExpenseDraft, outcome: Outcome) -> ConversationReply:
    if isinstance(outcome, NeedsInput):
        return expense_prompt_reply(draft, outcome.field, edit=ctx.query is not None)
    if isinstance(outcome, Ended):
        if outcome.user_message:
            return ConversationReply(
                ConversationHandler.END,
                (MessageAction(outcome.user_message, parse_mode="Markdown"),),
            )
        return ConversationReply(ConversationHandler.END)
    if isinstance(outcome, ReadyToConfirm):
        try:
            reply = expense_confirmation_reply(
                draft=draft,
                key=f"{ctx.user_id}_{ctx.message.message_id}",
                tg_name=ctx.tg_name,
                group_id=ctx.group_id,
                split_mode=outcome.split_mode,
                paid_for=outcome.paid_for,
                bot_data=ctx.session.bot_data,
                edit=ctx.query is not None,
            )
        except Exception as error:
            return error_reply(error)
        ctx.session.draft = None
        return reply
    raise AssertionError("unreachable add outcome")


async def _deliver_outcome(ctx: AddContext, draft: ExpenseDraft, outcome: Outcome) -> int:
    ctx.session.draft = draft
    return await _outcome_to_reply(ctx, draft, outcome).deliver(ctx.query, ctx.message)


async def _deliver(ctx: AddContext, reply: ConversationReply) -> int:
    return await reply.deliver(ctx.query, ctx.message)


async def _enter_with_text(ctx: AddContext, text: str) -> int:
    participants_map = gateway.group(ctx.group_id).directory.participants_map
    if parsed_title_amount := _parse_title_amount(text):
        draft, outcome = start_from_parsed(parsed_title_amount, participants_map)
        return await _deliver_outcome(ctx, draft, outcome)
    parsed = await parse_add_text(text, list(participants_map))
    if isinstance(parsed, ParseFailure):
        assert ctx.message.from_user is not None
        await notify_admin_llm_error(
            ctx.context, ctx.message.from_user, text, parsed.user_message, parsed.raw_response
        )
        return await _deliver(
            ctx,
            ConversationReply(
                ConversationHandler.END,
                (MessageAction(parsed.user_message, parse_mode="Markdown"),),
            ),
        )
    if parsed is None:
        return await _deliver(
            ctx,
            ConversationReply(
                ConversationHandler.END,
                (MessageAction(_FORMAT_HELP, parse_mode="Markdown"),),
            ),
        )
    draft, outcome = start_from_parsed(parsed, participants_map)
    return await _deliver_outcome(ctx, draft, outcome)


async def enter_add_with_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    group_id: str,
) -> int:
    ctx = _add_context(update, context, group_id=group_id)
    return await _enter_with_text(ctx, text.strip())


def _require_draft(ctx: AddContext) -> ExpenseDraft:
    draft = ctx.session.draft
    assert draft is not None
    return draft


async def interactive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text
    ctx = _add_context(update, context)
    draft = _require_draft(ctx)
    try:
        outcome = apply_title(draft, update.message.text)
    except Exception as error:
        return await _deliver(ctx, error_reply(error))
    return await _deliver_outcome(ctx, draft, outcome)


async def interactive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text
    ctx = _add_context(update, context)
    draft = _require_draft(ctx)
    try:
        outcome = apply_amount(draft, update.message.text)
    except Exception as error:
        return await _deliver(ctx, error_reply(error))
    if isinstance(outcome, Rejected):
        ctx.session.draft = draft
        return await _deliver(ctx, invalid_amount_reply(outcome.user_message))
    try:
        draft.participants_map = gateway.group(ctx.group_id).directory.participants_map
    except Exception as error:
        return await _deliver(ctx, error_reply(error))
    return await _deliver_outcome(ctx, draft, outcome)


async def interactive_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data
    ctx = _add_context(update, context, query=query)
    draft = _require_draft(ctx)
    try:
        outcome = apply_payer(draft, query.data[len(CB_PAYER) :])
    except Exception as error:
        return await _deliver(ctx, error_reply(error))
    return await _deliver_outcome(ctx, draft, outcome)


async def interactive_split_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data
    ctx = _add_context(update, context, query=query)
    draft = _require_draft(ctx)
    try:
        outcome = apply_split_mode(draft, query.data[len(CB_SPLIT_MODE) :])
    except Exception as error:
        return await _deliver(ctx, error_reply(error))
    return await _deliver_outcome(ctx, draft, outcome)


async def interactive_split_values(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message and update.message.text
    ctx = _add_context(update, context)
    draft = _require_draft(ctx)
    try:
        outcome = apply_split_values(draft, update.message.text)
    except Exception as error:
        return await _deliver(ctx, error_reply(error))
    if isinstance(outcome, Rejected):
        ctx.session.draft = draft
        return await _deliver(ctx, split_values_retry_reply(outcome.user_message))
    return await _deliver_outcome(ctx, draft, outcome)


async def interactive_payees(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query and query.data
    ctx = _add_context(update, context, query=query)
    draft = _require_draft(ctx)
    try:
        if query.data == CB_PAYEE_DONE:
            outcome = complete_payees(draft)
            if isinstance(outcome, Rejected):
                ctx.session.draft = draft
                return await _deliver(
                    ctx,
                    ConversationReply(PAYEES, (MessageAction(outcome.user_message, alert=True),)),
                )
        elif query.data == f"{CB_PAYEE}{CB_PAYEE_ALL}":
            outcome = toggle_all_payees(draft)
        else:
            outcome = toggle_payee(draft, query.data[len(CB_PAYEE) :])
    except Exception as error:
        return await _deliver(ctx, error_reply(error))
    return await _deliver_outcome(ctx, draft, outcome)


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not is_allowed_chat(update) or not update.message or not update.effective_user:
        return ConversationHandler.END

    session = Session(context.user_data, context.bot_data)
    session.draft = None
    group_id = resolve_group(update, context.user_data)
    if not group_id:
        if is_dm(update):
            if not configured_group_ids():
                await update.message.reply_text(
                    "No groups configured.",
                    reply_to_message_id=update.message.message_id,
                )
                return ConversationHandler.END
            session.pending_add_text = (update.message.text or "").strip()
            await update.message.reply_text(
                "Select a group first:",
                reply_markup=group_picker_keyboard(group_picker_options()),
                reply_to_message_id=update.message.message_id,
            )
            return SELECT_GROUP
        await update.message.reply_text(NO_GROUP_MSG, reply_to_message_id=update.message.message_id)
        return ConversationHandler.END

    payload = _command_payload(update.message.text or "")
    if payload is None:
        ctx = _add_context(update, context, group_id=group_id)
        draft, outcome = start_draft()
        return await _deliver_outcome(ctx, draft, outcome)
    return await enter_add_with_text(update, context, payload, group_id=group_id)


async def cancel_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message
    Session(context.user_data, context.bot_data).draft = None
    await update.message.reply_text("Cancelled.", reply_to_message_id=update.message.message_id)
    return ConversationHandler.END


async def interactive_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    session = Session(context.user_data, context.bot_data)
    assert query and query.data and update.effective_user

    if not query.data.startswith(CB_SELECT_GROUP):
        return SELECT_GROUP

    group_id = query.data[len(CB_SELECT_GROUP) :]
    session.active_group_id = group_id
    label = group_name(group_id)
    pending_add_text = session.pop_pending_add_text()
    if pending_add_text is None:
        await query.answer()
        await query.edit_message_text(f"Switched to: {label}")
        return ConversationHandler.END

    session.draft = None
    await query.answer()
    await query.edit_message_text(f"Group: {label}")
    message = cast(Message, query.message)
    ctx = _add_context(update, context, group_id=group_id, message=message)
    payload = _command_payload(pending_add_text)
    if payload is None:
        draft, outcome = start_draft()
        return await _deliver_outcome(ctx, draft, outcome)
    return await _enter_with_text(ctx, payload)
